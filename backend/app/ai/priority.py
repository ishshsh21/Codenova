"""
FR-14 Priority Engine — hybrid deterministic scoring.

PriorityScore = 30% DeadlineUrgency + 20% BusinessImpact + 15% BlockingDependency
              + 15% ExplicitUrgency + 10% ContextImportance + 10% EffortVsDeadline

Every factor is normalized to 0..1 and every score comes with a human-readable
explanation (TRD: "Every priority must have an explanation").

Class audience (ai/audience.py) is applied on top: mail addressed to the
user's own class gets a boost, and mail addressed to a different class is
capped at P4 (info) no matter how urgent its wording is.
"""
from datetime import datetime

from app.ai.audience import MINE, OTHER_CLASS

MY_CLASS_BOOST = 0.1

WEIGHTS = {
    "deadline_urgency": 0.30,
    "business_impact": 0.20,
    "blocking_dependency": 0.15,
    "explicit_urgency": 0.15,
    "context_importance": 0.10,
    "effort_vs_deadline": 0.10,
}

VIP_SENDER_HINTS = ("client", "ceo", "vp", "director", "head of")
URGENT_WORDS = ("asap", "urgent", "critical", "immediately", "blocking")


def _deadline_urgency(deadline: datetime | None, now: datetime) -> tuple[float, str | None]:
    if not deadline:
        return 0.1, None
    hours_left = (deadline - now).total_seconds() / 3600
    if hours_left <= 0:
        return 1.0, "Overdue"
    if hours_left <= 24:
        return 0.9, "Due today"
    if hours_left <= 72:
        return 0.6, "Due this week"
    if hours_left <= 168:
        return 0.4, "Due within a week"
    return 0.15, "Due later"


def _business_impact(sender_email: str, project: str | None, is_vip: bool = False) -> tuple[float, str | None]:
    lowered = sender_email.lower()
    if is_vip:
        return 0.95, "From a user-marked VIP sender"
    if any(hint in lowered for hint in VIP_SENDER_HINTS):
        return 0.85, "From a client/senior stakeholder"
    if project:
        return 0.5, f"Linked to project: {project}"
    return 0.3, None


def _blocking_dependency(is_blocking: bool, has_dependents: bool) -> tuple[float, str | None]:
    if is_blocking or has_dependents:
        return 0.9, "Blocks other work"
    return 0.1, None


def _explicit_urgency(text: str) -> tuple[float, str | None]:
    lowered = text.lower()
    hits = [w for w in URGENT_WORDS if w in lowered]
    if hits:
        return 0.85, f"Explicit urgency language ('{hits[0]}')"
    return 0.2, None


def _context_importance(thread_message_count: int, classification: str) -> tuple[float, str | None]:
    if classification == "FOLLOW_UP_REQUIRED" and thread_message_count > 1:
        return 0.7, f"Repeated follow-up across {thread_message_count} messages"
    if thread_message_count > 3:
        return 0.5, "Long, active thread"
    return 0.25, None


def _effort_vs_deadline(effort_minutes: int, deadline: datetime | None, now: datetime) -> tuple[float, str | None]:
    if not deadline:
        return 0.2, None
    hours_left = max((deadline - now).total_seconds() / 3600, 0.01)
    ratio = (effort_minutes / 60) / hours_left
    if ratio > 0.5:
        return 0.8, "Tight relative to remaining time"
    return 0.2, None


def score_task(
    *,
    text_for_urgency: str,
    sender_email: str,
    project: str | None,
    is_blocking: bool,
    has_dependents: bool,
    thread_message_count: int,
    classification: str,
    effort_minutes: int,
    deadline: datetime | None,
    is_vip: bool = False,
    audience: str = "GENERAL",
    audience_reason: str | None = None,
    now: datetime | None = None,
) -> tuple[float, str, list[str]]:
    now = now or datetime.utcnow()

    if audience == OTHER_CLASS:
        # Another class's deadline is not the user's deadline: don't let its
        # urgency words or due date leak into the user's priorities.
        return 0.05, "P4", [audience_reason or "Addressed to a different class"]

    du, du_reason = _deadline_urgency(deadline, now)
    bi, bi_reason = _business_impact(sender_email, project, is_vip)
    bd, bd_reason = _blocking_dependency(is_blocking, has_dependents)
    eu, eu_reason = _explicit_urgency(text_for_urgency)
    ci, ci_reason = _context_importance(thread_message_count, classification)
    ev, ev_reason = _effort_vs_deadline(effort_minutes, deadline, now)

    score = (
        du * WEIGHTS["deadline_urgency"]
        + bi * WEIGHTS["business_impact"]
        + bd * WEIGHTS["blocking_dependency"]
        + eu * WEIGHTS["explicit_urgency"]
        + ci * WEIGHTS["context_importance"]
        + ev * WEIGHTS["effort_vs_deadline"]
    )
    if audience == MINE:
        score += MY_CLASS_BOOST
    score = round(min(max(score, 0.0), 1.0), 3)

    if score >= 0.75:
        level = "P0"
    elif score >= 0.55:
        level = "P1"
    elif score >= 0.35:
        level = "P2"
    elif score >= 0.18:
        level = "P3"
    else:
        level = "P4"

    class_reason = audience_reason if audience == MINE else None
    reasons = [r for r in (class_reason, du_reason, bd_reason, eu_reason, bi_reason, ci_reason, ev_reason) if r]
    if not reasons:
        reasons = ["No strong urgency signals detected"]

    return score, level, reasons
