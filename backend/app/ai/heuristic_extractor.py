"""
Deterministic fallback extractor (FR-06..FR-11).
Used whenever no LLM API key is configured, and as a safety net if the LLM
call fails or returns invalid JSON — the pipeline must never hard-fail
processing (TRD Section 12: "LLM unavailable -> persist email, mark PENDING").

This is intentionally rule-based rather than a stub: it implements the same
classification/extraction/deadline/owner logic the LLM prompt asks for, just
with keyword heuristics instead of model reasoning, so the MVP is fully
demoable offline.
"""
import re
from datetime import datetime, timedelta

from app.ai.schemas import ExtractionResult

AUTOMATED_SENDERS = ("notifications@github.com", "noreply@", "no-reply@", "calendar-notification@google.com")
NEWSLETTER_HINTS = ("newsletter", "unsubscribe", "digest")

DEADLINE_PATTERNS = [
    (re.compile(r"\btoday\b", re.I), lambda now: now.replace(hour=23, minute=59, second=0, microsecond=0)),
    (re.compile(r"\btomorrow\b", re.I), lambda now: (now + timedelta(days=1)).replace(hour=23, minute=59)),
    (re.compile(r"\beod\b", re.I), lambda now: now.replace(hour=18, minute=0, second=0, microsecond=0)),
    (re.compile(r"\bcob\b", re.I), lambda now: now.replace(hour=18, minute=0, second=0, microsecond=0)),
    (re.compile(r"\basap\b", re.I), lambda now: now + timedelta(hours=4)),
    (re.compile(r"\bfriday\b", re.I), lambda now: _next_weekday(now, 4)),
    (re.compile(r"\bmonday\b", re.I), lambda now: _next_weekday(now, 0)),
    (re.compile(r"\bthursday\b", re.I), lambda now: _next_weekday(now, 3)),
]

UNRESOLVABLE_DEADLINE_PATTERNS = [
    re.compile(r"before the client meeting", re.I),
    re.compile(r"before the (demo|release|launch)", re.I),
]

ACTION_VERBS = {
    "approve": "APPROVE",
    "review": "REVIEW",
    "reject": "REJECT",
    "send": "SEND_DOCUMENT",
    "fix": "FIX_ISSUE",
    "create": "CREATE_DOCUMENT",
    "attend": "ATTEND_MEETING",
    "reply": "REPLY",
    "respond": "REPLY",
    "follow up": "FOLLOW_UP",
    "decide": "DECISION",
    "complete": "PROVIDE_INFORMATION",
}


def _next_weekday(now: datetime, target_weekday: int) -> datetime:
    days_ahead = (target_weekday - now.weekday()) % 7
    days_ahead = days_ahead or 7
    return (now + timedelta(days=days_ahead)).replace(hour=17, minute=0, second=0, microsecond=0)


def _detect_deadline(text: str, now: datetime) -> tuple[str | None, str | None, float]:
    for pattern in UNRESOLVABLE_DEADLINE_PATTERNS:
        m = pattern.search(text)
        if m:
            return None, m.group(0), 0.4  # FR-09: never invent an exact date; store raw text

    for pattern, resolver in DEADLINE_PATTERNS:
        m = pattern.search(text)
        if m:
            resolved = resolver(now)
            return resolved.isoformat(), m.group(0), 0.75

    explicit_date = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
    if explicit_date:
        return explicit_date.group(1), explicit_date.group(1), 0.95

    return None, None, 0.0


def _detect_owner(text: str, recipient_hint: str = "you") -> tuple[str, str, float]:
    lowered = text.lower()
    if re.search(r"\bcan you\b|\bcould you\b|\byou\b.*\?", lowered) or "please review" in lowered or "please approve" in lowered:
        return "CURRENT_USER", "You", 0.85
    name_match = re.search(r"\b([A-Z][a-z]+),\s+(please|can you|could you)\b", text)
    if name_match:
        return "OTHER_PERSON", name_match.group(1), 0.8
    if re.search(r"someone from|anyone (?:on|in|from)|team\b", lowered):
        return "TEAM_UNKNOWN", "Team", 0.5
    return "CURRENT_USER", "You", 0.4


def _detect_action_type(text: str) -> str:
    lowered = text.lower()
    for verb, action_type in ACTION_VERBS.items():
        if verb in lowered:
            return action_type
    return "OTHER"


def classify_and_extract(
    sender_email: str,
    subject: str,
    body: str,
    thread_message_count: int,
    now: datetime | None = None,
) -> ExtractionResult:
    now = now or datetime.utcnow()
    text = f"{subject}\n{body}"
    lowered = text.lower()

    # --- FR-06 Classification ---
    if any(sender_email.startswith(s) or s in sender_email for s in AUTOMATED_SENDERS):
        return ExtractionResult(
            classification="AUTOMATED_NOTIFICATION",
            classification_confidence=0.9,
            classification_evidence=f"Sender pattern matches automated system: {sender_email}",
        )

    if any(h in lowered for h in NEWSLETTER_HINTS) or "newsletter" in sender_email:
        return ExtractionResult(
            classification="NEWSLETTER",
            classification_confidence=0.85,
            classification_evidence="Contains newsletter/unsubscribe language",
        )

    if re.search(r"\bmeeting\b|\bsprint planning\b|\bcalendar\b", lowered) and not re.search(r"review|approve", lowered):
        return ExtractionResult(
            classification="MEETING_INFORMATION",
            classification_confidence=0.8,
            classification_evidence="References a scheduled meeting/event",
            is_actionable=True,
            task_title=f"Attend: {subject}",
            action_type="ATTEND_MEETING",
            task_confidence=0.7,
            owner_type="CURRENT_USER",
            owner_label="You",
            owner_confidence=0.6,
            estimated_effort_minutes=30,
        )

    if re.search(r"no further action|closed on our end|approved and closed|all set|resolved\b", lowered):
        return ExtractionResult(
            classification="COMPLETED",
            classification_confidence=0.8,
            classification_evidence="Message indicates the matter is resolved/closed",
        )

    if re.search(r"following up|any update|just checking in|circling back", lowered):
        classification = "FOLLOW_UP_REQUIRED"
    elif re.search(r"waiting on|pending your|when you get a chance", lowered):
        classification = "WAITING_FOR_OTHER_PERSON"
    elif re.search(r"can you|could you|please (review|approve|fix|send|create)|need your|before .* (today|tomorrow|friday|eod|cob)", lowered):
        classification = "ACTION_REQUIRED"
    elif re.search(r"fyi|just letting you know|heads up|closed for", lowered):
        return ExtractionResult(
            classification="FYI",
            classification_confidence=0.75,
            classification_evidence="Informational language ('FYI', 'heads up')",
        )
    else:
        classification = "POSSIBLE_TASK"

    deadline_iso, deadline_raw, deadline_conf = _detect_deadline(text, now)
    owner_type, owner_label, owner_conf = _detect_owner(text)
    action_type = _detect_action_type(text)
    is_blocking = bool(re.search(r"\bblock(ed|ing|s)?\b|before .* can (start|deploy|proceed)", lowered))

    title_source = re.sub(r"^(re:|fwd:)\s*", "", subject, flags=re.I).strip() or body[:60]
    task_title = title_source if len(title_source) > 3 else body[:60].strip()

    task_confidence = 0.9 if classification == "ACTION_REQUIRED" else 0.65
    if thread_message_count > 1 and classification == "FOLLOW_UP_REQUIRED":
        task_confidence = 0.85  # a repeated follow-up is strong evidence of a real pending task

    return ExtractionResult(
        classification=classification,
        classification_confidence=0.75,
        classification_evidence="Keyword/pattern heuristic match",
        is_actionable=owner_type == "CURRENT_USER",
        task_title=task_title,
        action_type=action_type,
        task_confidence=task_confidence,
        owner_type=owner_type,
        owner_label=owner_label,
        owner_confidence=owner_conf,
        deadline_iso=deadline_iso,
        deadline_raw=deadline_raw,
        deadline_confidence=deadline_conf,
        project=None,
        project_confidence=0.0,
        is_blocking=is_blocking,
        estimated_effort_minutes=45 if action_type in ("REVIEW", "CREATE_DOCUMENT", "FIX_ISSUE") else 20,
    )
