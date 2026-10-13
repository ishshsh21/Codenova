"""Gmail connection lifecycle and asynchronous scan endpoints."""
import logging
from datetime import datetime, date, timedelta

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException
from googleapiclient.errors import HttpError
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database import get_db, SessionLocal
from app.config import get_settings
from app.models import (
    User, GmailConnection, Notification, ScanRun, EmailMessage, EmailThread,
    Task, TaskSource, TaskDependency, TaskFeedback,
)
from app.security import get_current_user
from app.schemas import GmailStatusOut, ScanOut, ScanStartOut, NotificationOut, SyncRequestIn
from app.gmail.client import GmailRateLimitError, is_rate_limit_error
from app.gmail.sync import build_gmail_query, run_sync

router = APIRouter(prefix="/api/gmail", tags=["gmail"])
settings = get_settings()
logger = logging.getLogger("workday_agent.gmail")


def _queue_scan(db: Session, user: User, start_date: date | None, end_date: date | None) -> ScanRun:
    if not start_date and not end_date:
        end_date = datetime.utcnow().date()
        start_date = end_date - timedelta(days=user.default_scan_days)
    scan = ScanRun(
        user_id=user.id,
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


def _scan_error_message(exc: Exception) -> str:
    """What the Sync page shows for a failed scan: plain words, not Google's raw error dump."""
    if isinstance(exc, GmailRateLimitError) or (isinstance(exc, HttpError) and is_rate_limit_error(exc)):
        return "Gmail is limiting how fast we can read your inbox. Wait a minute, then press Run again."
    if isinstance(exc, HttpError):
        return f"Gmail returned an error (HTTP {exc.resp.status}). Try again in a few minutes."
    return str(exc)[:1000]


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

        def update_progress(stage: str, progress: int, total: int):
            current = db.get(ScanRun, scan_id)
            if current:
                current.stage = stage
                current.progress = progress
                current.progress_total = total
                db.commit()

        result = run_sync(
            db, user, start_date=start_date, end_date=end_date,
            progress_callback=update_progress,
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
        if user.notify_scan_completion:
            db.add(Notification(
                user_id=user_id,
                scan_id=scan.id,
                kind="SUCCESS",
                title="Scan completed",
                message=(
                    f"{scan.messages_fetched} emails scanned, {scan.tasks_created} new "
                    f"task{'s' if scan.tasks_created != 1 else ''} found."
                    + (
                        f" {result['other_class_messages']} for other classes went to FYI."
                        if result["other_class_messages"] else ""
                    )
                ),
            ))
        db.commit()
    except Exception as exc:
        db.rollback()
        scan = db.get(ScanRun, scan_id)
        if not scan:
            return
        scan.status = "FAILED"
        scan.error_message = _scan_error_message(exc)
        scan.completed_at = datetime.utcnow()
        scan.stage = "FAILED"
        db.add(Notification(
            user_id=user_id,
            scan_id=scan_id,
            kind="ERROR",
            title="Scan failed",
            message="We could not finish scanning Gmail. Check the backend logs and try again.",
        ))
        db.commit()
        logger.exception("Gmail scan %s failed", scan_id)
    finally:
        db.close()


@router.get("/status", response_model=GmailStatusOut)
def status(user: User = Depends(get_current_user)):
    conn = user.gmail_connection
    if not conn:
        return GmailStatusOut(connected=False)
    return GmailStatusOut(
        connected=True,
        google_account_email=conn.google_account_email,
        last_synced_at=conn.last_synced_at,
        watch_active=bool(conn.watch_history_id),
    )


@router.post("/connect")
def connect(user: User = Depends(get_current_user)):
    """Real connection happens via /api/auth/google (OAuth). This endpoint
    just confirms readiness — kept for TRD REST-surface parity."""
    if not user.gmail_connection:
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
    if not user.gmail_connection:
        raise HTTPException(
            status_code=400,
            detail="No Gmail account connected. Sign in with Google (Connect Gmail) before syncing.",
        )

    scan = _queue_scan(db, user, payload.start_date, payload.end_date)
    background_tasks.add_task(_run_scan, scan.id, user.id, scan.start_date, scan.end_date)
    return scan


@router.get("/scans", response_model=list[ScanOut])
def list_scans(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return (
        db.query(ScanRun)
        .filter_by(user_id=user.id)
        .order_by(ScanRun.created_at.desc())
        .limit(100)
        .all()
    )


@router.get("/scans/{scan_id}", response_model=ScanOut)
def get_scan(scan_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    scan = db.query(ScanRun).filter_by(id=scan_id, user_id=user.id).first()
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")
    return scan


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
    if not user.gmail_connection:
        raise HTTPException(status_code=400, detail="No Gmail account connected. Sign in with Google before rerunning.")
    scan = _queue_scan(db, user, previous.start_date, previous.end_date)
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


@router.delete("/disconnect")
def disconnect(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Section 11 Privacy — disconnect/delete functionality."""
    conn = user.gmail_connection
    if conn:
        db.delete(conn)
        db.commit()
    return {"disconnected": True}
