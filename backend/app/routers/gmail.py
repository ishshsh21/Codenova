"""Gmail connection lifecycle and asynchronous scan endpoints."""
import logging
from datetime import datetime, date, timedelta

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database import get_db, SessionLocal
from app.config import get_settings
from app.models import (
    User, GmailConnection, Notification, ScanRun, EmailMessage, EmailThread,
    Task, TaskSource, TaskDependency, TaskFeedback,
)
from app.security import get_current_user
from app.schemas import (
    GmailStatusOut, ScanOut, ScanStartOut, NotificationOut, SyncRequestIn,
    GmailAccountOut, GmailAccountsOut, GmailAccountConnectIn, GmailAccountUpdateIn, GmailAccountSelectIn,
)
from app.auth.flows import clean_label, start_flow
from app.gmail.accounts import ALL, scope_connections, selected_account_id
from app.gmail.client import GmailRateLimitError
from app.gmail.sync import build_gmail_query, run_sync

router = APIRouter(prefix="/api/gmail", tags=["gmail"])
settings = get_settings()
logger = logging.getLogger("workday_agent.gmail")


MAX_ACCOUNTS = 10

RATE_LIMIT_NONE_FETCHED = (
    "Gmail's rate limit was reached before any emails could be downloaded. "
    "Wait about a minute, then rerun the scan."
)
RATE_LIMIT_PARTIAL = (
    "Gmail's rate limit was reached, so {n} email{s} weren't downloaded this time. "
    "Everything fetched so far was saved. Wait about a minute, then rerun the scan to continue."
)


def _queue_scan(
    db: Session, user: User, start_date: date | None, end_date: date | None, connection_id: str | None = None,
) -> ScanRun:
    if not start_date and not end_date:
        end_date = datetime.utcnow().date()
        start_date = end_date - timedelta(days=user.default_scan_days)
    scan = ScanRun(
        user_id=user.id,
        connection_id=connection_id,
        status="QUEUED",
        start_date=start_date,
        end_date=end_date,
        gmail_query=build_gmail_query(start_date, end_date),
    )
    db.add(scan)
    db.flush()
    db.add(Notification(
        user_id=user.id,
        scan_id=scan.id,
        kind="INFO",
        title="Scan started",
        message=f"Scanning Gmail with query: {scan.gmail_query}",
    ))
    db.commit()
    db.refresh(scan)
    return scan


def _run_scan(scan_id: str, user_id: str, start_date: date | None, end_date: date | None):
    """Run outside the request and retain both success and failure state."""
    db = SessionLocal()
    scan = db.get(ScanRun, scan_id)
    if not scan:
        db.close()
        return
    try:
        scan.status = "RUNNING"
        scan.started_at = datetime.utcnow()
        db.commit()

        user = db.get(User, user_id)
        if not user:
            return
        connection_id = scan.connection_id or ALL  # NULL on a scan means every connected account

        def update_progress(stage: str, progress: int, total: int):
            current = db.get(ScanRun, scan_id)
            if current:
                current.stage = stage
                current.progress = progress
                current.progress_total = total
                db.commit()

        result = run_sync(
            db, user, start_date=start_date, end_date=end_date,
            progress_callback=update_progress, connection_id=connection_id,
        )
        scan = db.get(ScanRun, scan_id)
        # The user may have deleted this scan while it was running.
        if not scan:
            return
        scan.status = "COMPLETED"
        scan.messages_fetched = result["messages_fetched"]
        scan.messages_processed = result["messages_processed"]
        scan.tasks_created = result["tasks_created"]
        scan.tasks_updated = result["tasks_updated"]
        scan.duration_ms = result["duration_ms"]
        scan.stage = "COMPLETED"
        scan.progress = scan.progress_total or scan.messages_fetched
        scan.progress_total = scan.progress_total or scan.messages_fetched
        scan.completed_at = datetime.utcnow()
        unfetched = result.get("messages_unfetched", 0)
        if unfetched:
            # Cut short by Gmail's per-minute quota: what was fetched is saved, and a rerun
            # only downloads the rest (already-imported emails are not fetched again).
            scan.status = "FAILED"
            scan.stage = "FAILED"
            scan.error_message = RATE_LIMIT_PARTIAL.format(n=unfetched, s="" if unfetched == 1 else "s")
            db.add(Notification(
                user_id=user_id, scan_id=scan.id, kind="ERROR", title="Scan paused by Gmail rate limit",
                message=scan.error_message,
            ))
        elif user.notify_scan_completion:
            db.add(Notification(
                user_id=user_id,
                scan_id=scan.id,
                kind="SUCCESS",
                title="Scan completed",
                message=(
                    f"{scan.messages_fetched} emails scanned, {scan.tasks_created} new "
                    f"task{'s' if scan.tasks_created != 1 else ''} found."
                ),
            ))
        db.commit()
    except Exception as exc:
        db.rollback()
        scan = db.get(ScanRun, scan_id)
        if not scan:
            return
        rate_limited = isinstance(exc, GmailRateLimitError)
        scan.status = "FAILED"
        scan.error_message = RATE_LIMIT_NONE_FETCHED if rate_limited else str(exc)[:1000]
        scan.completed_at = datetime.utcnow()
        scan.stage = "FAILED"
        db.add(Notification(
            user_id=user_id,
            scan_id=scan_id,
            kind="ERROR",
            title="Scan paused by Gmail rate limit" if rate_limited else "Scan failed",
            message=RATE_LIMIT_NONE_FETCHED if rate_limited else "We could not finish scanning Gmail. Check the backend logs and try again.",
        ))
        db.commit()
        logger.exception("Gmail scan %s failed", scan_id)
    finally:
        db.close()


@router.get("/status", response_model=GmailStatusOut)
def status(user: User = Depends(get_current_user)):
    if not user.gmail_connections:
        return GmailStatusOut(connected=False)
    scope = scope_connections(user)
    conn = scope[0] if len(scope) == 1 else user.gmail_connection
    return GmailStatusOut(
        connected=True,
        google_account_email=conn.google_account_email,
        last_synced_at=max((c.last_synced_at for c in scope if c.last_synced_at), default=None),
        watch_active=bool(conn.watch_history_id),
    )


@router.post("/connect")
def connect(user: User = Depends(get_current_user)):
    """Real connection happens via /api/auth/google (OAuth). This endpoint
    just confirms readiness — kept for TRD REST-surface parity."""
    if not user.gmail_connections:
        raise HTTPException(400, "No Gmail connection — complete OAuth via /api/auth/google first")
    return {"connected": True}


@router.post("/sync", response_model=ScanStartOut)
def sync(
    background_tasks: BackgroundTasks,
    payload: SyncRequestIn = Body(default=SyncRequestIn()),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Queue a scan and return immediately so the dashboard stays usable."""
    if not user.gmail_connections:
        raise HTTPException(
            status_code=400,
            detail="No Gmail account connected. Sign in with Google (Connect Gmail) before syncing.",
        )
    wanted = payload.account_id or selected_account_id(user)
    if wanted != ALL and not scope_connections(user, wanted):
        raise HTTPException(404, "Gmail account not found")

    scan = _queue_scan(db, user, payload.start_date, payload.end_date, None if wanted == ALL else wanted)
    background_tasks.add_task(_run_scan, scan.id, user.id, scan.start_date, scan.end_date)
    return scan


def _scan_out(scan: ScanRun, user: User) -> ScanOut:
    out = ScanOut.model_validate(scan, from_attributes=True)
    account = next((c for c in user.gmail_connections if c.id == scan.connection_id), None)
    if account:
        out.account_email, out.account_label = account.google_account_email, account.label or None
    return out


@router.get("/scans", response_model=list[ScanOut])
def list_scans(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = db.query(ScanRun).filter_by(user_id=user.id)
    selected = selected_account_id(user)
    if selected != ALL:
        query = query.filter(ScanRun.connection_id == selected)
    return [_scan_out(scan, user) for scan in query.order_by(ScanRun.created_at.desc()).limit(100).all()]


@router.get("/scans/{scan_id}", response_model=ScanOut)
def get_scan(scan_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    scan = db.query(ScanRun).filter_by(id=scan_id, user_id=user.id).first()
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")
    return _scan_out(scan, user)


@router.post("/scans/{scan_id}/rerun", response_model=ScanStartOut)
def rerun_scan(
    scan_id: str,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    previous = db.query(ScanRun).filter_by(id=scan_id, user_id=user.id).first()
    if not previous:
        raise HTTPException(status_code=404, detail="Scan not found")
    if not user.gmail_connections:
        raise HTTPException(status_code=400, detail="No Gmail account connected. Sign in with Google before rerunning.")
    if previous.connection_id and not scope_connections(user, previous.connection_id):
        raise HTTPException(status_code=400, detail="The Gmail account for this scan is no longer connected.")
    scan = _queue_scan(db, user, previous.start_date, previous.end_date, previous.connection_id)
    background_tasks.add_task(_run_scan, scan.id, user.id, scan.start_date, scan.end_date)
    return scan


@router.delete("/scans/{scan_id}")
def delete_scan(scan_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    scan = db.query(ScanRun).filter_by(id=scan_id, user_id=user.id).first()
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")
    db.query(Notification).filter_by(scan_id=scan.id, user_id=user.id).delete(synchronize_session=False)
    db.delete(scan)
    db.commit()
    return {"deleted": True}


@router.get("/notifications", response_model=list[NotificationOut])
def list_notifications(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return (
        db.query(Notification)
        .filter_by(user_id=user.id)
        .order_by(Notification.created_at.desc())
        .limit(100)
        .all()
    )


@router.post("/notifications/read-all")
def mark_notifications_read(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.query(Notification).filter_by(user_id=user.id, is_read=False).update(
        {Notification.is_read: True}, synchronize_session=False
    )
    db.commit()
    return {"ok": True}


@router.post("/watch")
def watch(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """FR-03 — stubbed for MVP (documented as Could-Have / requires a public
    Pub/Sub push endpoint). Returns a clear not-implemented response rather
    than silently no-op'ing."""
    if not user.gmail_connection:
        raise HTTPException(400, "No Gmail connection — complete OAuth via /api/auth/google first")
    raise HTTPException(501, "Gmail watch (Pub/Sub push) is not implemented in this MVP — use POST /api/gmail/sync to refresh manually.")


def _remove_connection(db: Session, user: User, conn: GmailConnection) -> None:
    if user.selected_gmail_account == conn.id:
        user.selected_gmail_account = None
    db.delete(conn)
    db.commit()


@router.delete("/disconnect")
def disconnect(account_id: str | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Section 11 Privacy — disconnect/delete functionality. Without `account_id`
    this removes the account used to sign in, as it always did."""
    conn = (
        next((c for c in user.gmail_connections if c.id == account_id), None) if account_id else user.gmail_connection
    )
    if conn:
        _remove_connection(db, user, conn)
    return {"disconnected": True}


# ---------- Multiple Gmail accounts ----------

def _accounts_out(user: User) -> GmailAccountsOut:
    ordered = sorted(user.gmail_connections, key=lambda c: (not c.is_primary, c.created_at))
    return GmailAccountsOut(
        accounts=[
            GmailAccountOut(
                id=c.id, email=c.google_account_email, label=c.label or "",
                is_primary=c.is_primary, last_synced_at=c.last_synced_at,
            )
            for c in ordered
        ],
        selected=selected_account_id(user),
    )


def _account_or_404(user: User, account_id: str) -> GmailConnection:
    conn = next((c for c in user.gmail_connections if c.id == account_id), None)
    if not conn:
        raise HTTPException(404, "Gmail account not found")
    return conn


@router.get("/accounts", response_model=GmailAccountsOut)
def list_accounts(user: User = Depends(get_current_user)):
    return _accounts_out(user)


@router.post("/accounts/connect")
def connect_account(payload: GmailAccountConnectIn = Body(default=GmailAccountConnectIn()), user: User = Depends(get_current_user)):
    """Start Google consent for another Gmail account (read-only, its own refresh token)."""
    if len(user.gmail_connections) >= MAX_ACCOUNTS:
        raise HTTPException(400, f"You can connect up to {MAX_ACCOUNTS} Gmail accounts.")
    return {"authorization_url": start_flow("gmail_account", user, settings.gmail_scopes, payload.label)}


@router.put("/accounts/selected", response_model=GmailAccountsOut)
def select_account(payload: GmailAccountSelectIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if payload.account_id != ALL:
        _account_or_404(user, payload.account_id)
    user.selected_gmail_account = payload.account_id
    db.commit()
    return _accounts_out(user)


@router.patch("/accounts/{account_id}", response_model=GmailAccountOut)
def rename_account(account_id: str, payload: GmailAccountUpdateIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    conn = _account_or_404(user, account_id)
    conn.label = clean_label(payload.label)
    db.commit()
    return GmailAccountOut(
        id=conn.id, email=conn.google_account_email, label=conn.label,
        is_primary=conn.is_primary, last_synced_at=conn.last_synced_at,
    )


@router.delete("/accounts/{account_id}")
def remove_account(account_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Disconnect one account. Emails and tasks already imported from it are kept."""
    _remove_connection(db, user, _account_or_404(user, account_id))
    return {"removed": True}
