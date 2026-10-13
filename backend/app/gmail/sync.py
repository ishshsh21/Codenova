"""
Orchestrates FR-02 (initial sync) / FR-05 (thread reconstruction) /
FR-06..FR-14 (classification through priority) end to end, against the
signed-in user's real Gmail account via GmailClient.
"""
from datetime import datetime, date, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
from typing import Callable

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.config import get_settings
from app.gmail.mime_parser import extract_body_from_payload, parse_header, parse_sender
from app.gmail.client import GmailClient
from app.ai.llm_extractor import classify_and_extract_llm
from app.ai.priority import score_task
from app.ai.dedup import find_duplicate
from app.ai.dependencies import extract_dependency_phrases
from app.models import (
    User, EmailMessage, EmailThread, Task, TaskSource, TaskDependency,
    TaskStatus, SourceRelationship,
)
from app.security import decrypt_token

settings = get_settings()
_gmail_clients = threading.local()


def _thread_gmail_client(refresh_token: str) -> GmailClient:
    client = getattr(_gmail_clients, "client", None)
    if client is None or getattr(_gmail_clients, "refresh_token", None) != refresh_token:
        client = GmailClient(refresh_token)
        _gmail_clients.client = client
        _gmail_clients.refresh_token = refresh_token
    return client


def _fetch_one_email(refresh_token: str, ref) -> dict:
    raw = _thread_gmail_client(refresh_token).get_message(ref.id)
    payload = raw.get("payload", {})
    headers = payload.get("headers", [])
    body, has_attachments = extract_body_from_payload(payload)
    sender_name, sender_email = parse_sender(parse_header(headers, "From"))
    return {
        "gmail_message_id": raw["id"],
        "gmail_thread_id": raw["threadId"],
        "internal_date": datetime.utcfromtimestamp(int(raw.get("internalDate", "0")) / 1000),
        "sender_name": sender_name,
        "sender_email": sender_email,
        "subject": parse_header(headers, "Subject"),
        "snippet": raw.get("snippet", ""),
        "normalized_body": body,
        "has_attachments": has_attachments,
        "labels": raw.get("labelIds", []),
    }


def _sender_matches(sender: str, rules: list[str]) -> bool:
    sender = sender.lower()
    return any(rule.lower().strip() and (rule.lower().strip() in sender) for rule in rules)


def build_gmail_query(start_date: date | None, end_date: date | None) -> str:
    """
    Translates a user-selected [start_date, end_date] scan window into a
    Gmail search query using the `after:`/`before:` operators (both are
    calendar-day granularity in Gmail's search syntax, in the account's own
    timezone). `before:` is exclusive of that day, so end_date is bumped by
    one day to make the range inclusive of the selected end date.

    Falls back to `settings.default_sync_query` (newer_than:30d) when no
    range is given, preserving the previous default behavior.
    """
    if start_date and end_date:
        after = start_date.strftime("%Y/%m/%d")
        before = (end_date + timedelta(days=1)).strftime("%Y/%m/%d")
        return f"after:{after} before:{before}"
    if start_date:
        return f"after:{start_date.strftime('%Y/%m/%d')}"
    if end_date:
        before = (end_date + timedelta(days=1)).strftime("%Y/%m/%d")
        return f"before:{before}"
    return settings.default_sync_query


def _normalized_email_records_gmail(
    client: GmailClient, refresh_token: str, query: str, limit: int,
    progress_callback: Callable[[str, int, int], None] | None = None,
) -> list[dict]:
    refs = client.list_message_ids(query, limit)
    records = []
    with ThreadPoolExecutor(max_workers=settings.gmail_fetch_workers) as executor:
        futures = [executor.submit(_fetch_one_email, refresh_token, ref) for ref in refs]
        try:
            for index, future in enumerate(as_completed(futures), start=1):
                records.append(future.result())
                if progress_callback:
                    progress_callback("FETCHING_EMAILS", index, len(refs))
        except BaseException:
            # Once a fetch fails for good, don't let the queued ones keep
            # hitting a quota we've already exhausted.
            for future in futures:
                future.cancel()
            raise
    return records


def run_sync(
    db: Session,
    user: User,
    start_date: date | None = None,
    end_date: date | None = None,
    progress_callback: Callable[[str, int, int], None] | None = None,
) -> dict:
    started = datetime.utcnow()

    # ---- Fetch (FR-02) ----
    if not user.gmail_connection:
        raise HTTPException(
            status_code=400,
            detail="No Gmail account connected. Sign in with Google (Connect Gmail) before syncing.",
        )

    gmail_query = build_gmail_query(start_date, end_date)

    refresh_token = decrypt_token(user.gmail_connection.encrypted_refresh_token)
    client = GmailClient(refresh_token)
    if progress_callback:
        progress_callback("FETCHING_EMAILS", 0, 0)
    records = _normalized_email_records_gmail(
        client, refresh_token, gmail_query, settings.max_messages_per_sync, progress_callback
    )

    messages_fetched = len(records)
    messages_processed = 0
    tasks_created = 0
    tasks_updated = 0

    # ---- Persist + thread reconstruction (FR-05) ----
    thread_counts: dict[str, int] = {}
    for r in records:
        if _sender_matches(r["sender_email"], user.ignored_senders or []):
            continue
        thread_counts[r["gmail_thread_id"]] = thread_counts.get(r["gmail_thread_id"], 0) + 1

    for gmail_thread_id, count in thread_counts.items():
        thread = (
            db.query(EmailThread)
            .filter_by(user_id=user.id, gmail_thread_id=gmail_thread_id)
            .first()
        )
        subject = next((r["subject"] for r in records if r["gmail_thread_id"] == gmail_thread_id), "")
        if not thread:
            thread = EmailThread(user_id=user.id, gmail_thread_id=gmail_thread_id, subject=subject)
            db.add(thread)
        thread.message_count = count
        thread.last_message_at = max(
            (r["internal_date"] for r in records if r["gmail_thread_id"] == gmail_thread_id), default=None
        )
    db.commit()

    # Sort chronologically so "latest message + thread context" (FR-05) is honored.
    records.sort(key=lambda r: r["internal_date"])

    existing_ids = {
        message_id for (message_id,) in db.query(EmailMessage.gmail_message_id)
        .filter(EmailMessage.user_id == user.id)
        .filter(EmailMessage.gmail_message_id.in_([r["gmail_message_id"] for r in records]))
        .all()
    }
    records_to_process = [
        r for r in records
        if r["gmail_message_id"] not in existing_ids
        and not _sender_matches(r["sender_email"], user.ignored_senders or [])
    ]

    # AI calls are independent, so run them concurrently while keeping the
    # subsequent SQL writes ordered in this thread.
    extractions = {}
    with ThreadPoolExecutor(max_workers=settings.sync_worker_count) as executor:
        futures = {
            executor.submit(
                classify_and_extract_llm,
                sender_email=r["sender_email"], subject=r["subject"],
                body=r["normalized_body"],
                thread_message_count=thread_counts[r["gmail_thread_id"]], now=started,
            ): r["gmail_message_id"]
            for r in records_to_process
        }
        for index, future in enumerate(as_completed(futures), start=1):
            extractions[futures[future]] = future.result()
            if progress_callback:
                progress_callback("PROCESSING_EMAILS", index, len(records_to_process))

    open_tasks_cache: list[dict] = [
        {"id": t.id, "title": t.title}
        for t in db.query(Task).filter_by(user_id=user.id, status=TaskStatus.OPEN.value).all()
    ]

    pending_dependency_links: list[tuple[str, list[str]]] = []  # (task_id, blocking_phrases)

    for r in records_to_process:

        thread_count = thread_counts[r["gmail_thread_id"]]

        # ---- FR-06..FR-11: classification + extraction ----
        extraction = extractions[r["gmail_message_id"]]

        msg = EmailMessage(
            user_id=user.id,
            gmail_message_id=r["gmail_message_id"],
            gmail_thread_id=r["gmail_thread_id"],
            internal_date=r["internal_date"],
            sender_email=r["sender_email"],
            sender_name=r["sender_name"],
            subject=r["subject"],
            snippet=r["snippet"],
            normalized_body=r["normalized_body"],
            labels=r["labels"],
            has_attachments=r["has_attachments"],
            classification=extraction.classification,
            classification_confidence=extraction.classification_confidence,
            classification_evidence=extraction.classification_evidence,
            processing_status="PROCESSED",
        )
        db.add(msg)
        db.flush()
        messages_processed += 1

        if not (extraction.is_actionable and extraction.task_title):
            continue

        deadline_dt = None
        if extraction.deadline_iso:
            try:
                deadline_dt = datetime.fromisoformat(extraction.deadline_iso)
            except ValueError:
                deadline_dt = None

        # ---- FR-12: deduplication ----
        dup = find_duplicate(extraction.task_title, open_tasks_cache)
        if dup:
            task = db.get(Task, dup["id"])
            db.add(TaskSource(
                task_id=task.id, message_id=msg.id,
                relationship_type=SourceRelationship.FOLLOW_UP.value,
            ))
            tasks_updated += 1
        else:
            task = Task(
                user_id=user.id,
                title=extraction.task_title,
                description=r["normalized_body"][:500],
                status=TaskStatus.OPEN.value,
                action_type=extraction.action_type or "OTHER",
                deadline=deadline_dt,
                deadline_raw=extraction.deadline_raw,
                deadline_confidence=extraction.deadline_confidence,
                owner_type=extraction.owner_type or "CURRENT_USER",
                owner_label=extraction.owner_label,
                project=extraction.project,
                project_confidence=extraction.project_confidence,
                estimated_effort_minutes=extraction.estimated_effort_minutes,
                confidence=extraction.task_confidence,
                is_blocking=extraction.is_blocking,
            )
            db.add(task)
            db.flush()
            db.add(TaskSource(
                task_id=task.id, message_id=msg.id,
                relationship_type=SourceRelationship.ORIGIN.value,
            ))
            open_tasks_cache.append({"id": task.id, "title": task.title})
            tasks_created += 1

        # ---- FR-13: dependency phrase capture (linked after full pass) ----
        phrases = extract_dependency_phrases(r["normalized_body"])
        if phrases:
            pending_dependency_links.append((task.id, phrases))

    db.commit()

    # ---- FR-13: link dependencies now that all tasks in this sync exist ----
    all_open_tasks = db.query(Task).filter_by(user_id=user.id, status=TaskStatus.OPEN.value).all()
    for task_id, phrases in pending_dependency_links:
        for phrase in phrases:
            for candidate in all_open_tasks:
                if candidate.id == task_id:
                    continue
                if any(word in candidate.title.lower() for word in phrase.lower().split() if len(word) > 3):
                    db.add(TaskDependency(
                        task_id=task_id, depends_on_task_id=candidate.id,
                        relationship_type="BLOCKS", confidence=0.5,
                    ))
                    dep_task = db.get(Task, task_id)
                    dep_task.is_blocking = True
    db.commit()

    # ---- FR-14: (re)score priority for all open tasks ----
    if progress_callback:
        progress_callback("BUILDING_AGENDA", messages_fetched, messages_fetched)
    dependents_of: dict[str, int] = {}
    for dep in db.query(TaskDependency).all():
        dependents_of[dep.depends_on_task_id] = dependents_of.get(dep.depends_on_task_id, 0) + 1

    for task in db.query(Task).filter_by(user_id=user.id, status=TaskStatus.OPEN.value).all():
        source_msg = (
            db.query(EmailMessage)
            .join(TaskSource, TaskSource.message_id == EmailMessage.id)
            .filter(TaskSource.task_id == task.id)
            .order_by(EmailMessage.internal_date.desc())
            .first()
        )
        thread_count = thread_counts.get(source_msg.gmail_thread_id, 1) if source_msg else 1
        score, level, reasons = score_task(
            text_for_urgency=f"{task.title} {task.description}",
            sender_email=source_msg.sender_email if source_msg else "",
            project=task.project,
            is_blocking=task.is_blocking,
            has_dependents=dependents_of.get(task.id, 0) > 0,
            thread_message_count=thread_count,
            classification=source_msg.classification if source_msg else "",
            effort_minutes=task.estimated_effort_minutes,
            deadline=task.deadline,
            now=started,
            is_vip=_sender_matches(source_msg.sender_email if source_msg else "", user.vip_senders or []),
        )
        task.priority_score = score
        task.priority = level
        task.priority_reasons = reasons
    db.commit()

    if user.gmail_connection:
        user.gmail_connection.last_synced_at = datetime.utcnow()
        db.commit()

    duration_ms = int((datetime.utcnow() - started).total_seconds() * 1000)
    return {
        "messages_fetched": messages_fetched,
        "messages_processed": messages_processed,
        "tasks_created": tasks_created,
        "tasks_updated": tasks_updated,
        "duration_ms": duration_ms,
        "start_date": start_date,
        "end_date": end_date,
        "gmail_query": gmail_query,
    }
