from datetime import datetime, date
from typing import Optional, Any

from pydantic import BaseModel, Field, model_validator


class UserOut(BaseModel):
    id: str
    email: str
    name: str
    timezone: str
    workday_start: str
    workday_end: str
    default_scan_days: int
    notify_scan_completion: bool
    vip_senders: list[str] = []
    ignored_senders: list[str] = []

    class Config:
        from_attributes = True


class GmailStatusOut(BaseModel):
    connected: bool
    google_account_email: Optional[str] = None
    last_synced_at: Optional[datetime] = None
    watch_active: bool = False


class SyncRequestIn(BaseModel):
    """Optional scan window for POST /api/gmail/sync. Omit both fields (or
    send an empty body) to fall back to the default `newer_than:30d` scan."""
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    account_id: Optional[str] = None  # a connected account's id, or "all"; default: the selected account

    @model_validator(mode="after")
    def _validate_range(self):
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("start_date must be on or before end_date")
        return self


class SyncResultOut(BaseModel):
    messages_fetched: int
    messages_processed: int
    tasks_created: int
    tasks_updated: int
    duration_ms: int
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    gmail_query: str


class ScanStartOut(BaseModel):
    id: str
    status: str
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    gmail_query: str
    created_at: datetime


class ScanOut(ScanStartOut):
    messages_fetched: int
    messages_processed: int
    tasks_created: int
    tasks_updated: int
    duration_ms: int
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    stage: str
    progress: int
    progress_total: int
    connection_id: Optional[str] = None
    account_email: Optional[str] = None
    account_label: Optional[str] = None


class NotificationOut(BaseModel):
    id: str
    scan_id: Optional[str] = None
    kind: str
    title: str
    message: str
    is_read: bool
    created_at: datetime

    class Config:
        from_attributes = True


class TaskSourceOut(BaseModel):
    message_id: str
    gmail_thread_id: str
    internal_date: Optional[datetime] = None
    gmail_url: str
    subject: str
    sender_name: str
    sender_email: str
    snippet: str
    relationship_type: str


class TaskOut(BaseModel):
    id: str
    title: str
    description: str
    status: str
    priority: str
    priority_score: float
    priority_reasons: list[str]
    action_type: str
    deadline: Optional[datetime] = None
    deadline_raw: Optional[str] = None
    deadline_confidence: float
    owner_type: str
    owner_label: str
    project: Optional[str] = None
    project_confidence: float
    estimated_effort_minutes: int
    confidence: float
    is_blocking: bool
    notes: str
    snoozed_until: Optional[datetime] = None
    depends_on: list[str] = []
    sources: list[TaskSourceOut] = []
    calendar_synced: bool = False
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class TaskUpdateIn(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[str] = None
    deadline: Optional[datetime] = None
    project: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None
    snoozed_until: Optional[datetime] = None


class UserSettingsIn(BaseModel):
    timezone: Optional[str] = None
    workday_start: Optional[str] = None
    workday_end: Optional[str] = None
    default_scan_days: Optional[int] = None
    notify_scan_completion: Optional[bool] = None
    vip_senders: Optional[list[str]] = None
    ignored_senders: Optional[list[str]] = None


class DataSummaryOut(BaseModel):
    imported_emails: int
    tasks: int
    scans: int
    notifications: int
    gmail_connected: bool
    gmail_scopes: list[str]


class TaskFeedbackIn(BaseModel):
    feedback_type: str
    new_value: Optional[dict[str, Any]] = None


class AgendaTaskOut(BaseModel):
    id: str
    title: str
    priority: str
    priority_score: float
    deadline: Optional[datetime] = None
    estimated_effort_minutes: int
    blocking: bool
    reason: list[str]
    scheduled_time: Optional[str] = None
    source_thread_id: Optional[str] = None


class DailyAgendaOut(BaseModel):
    date: str
    summary: dict[str, int]
    task_ids: dict[str, list[str]]
    timeline: list[AgendaTaskOut]
    no_action_count: int


class WeeklyAgendaOut(BaseModel):
    week_start: str
    week_end: str
    days: dict[str, list[AgendaTaskOut]]
    later: list[AgendaTaskOut]


class AssistantMessageIn(BaseModel):
    role: str
    content: str


class AssistantChatIn(BaseModel):
    message: str
    history: list[AssistantMessageIn] = Field(default_factory=list)


class AssistantChatOut(BaseModel):
    message: str
    action_taken: Optional[str] = None


# ---------- Google Calendar (Today) ----------

class CalendarStatusOut(BaseModel):
    connected: bool
    google_account_email: Optional[str] = None
    last_synced_at: Optional[datetime] = None
    needs_reauth: bool = False
    error: Optional[str] = None


class CalendarEventOut(BaseModel):
    id: str
    title: str
    start: datetime
    end: datetime
    all_day: bool
    location: str = ""
    html_link: str = ""
    origin: str


class CalendarConflictOut(BaseModel):
    task_id: str
    title: str
    conflicts_with: list[dict[str, Any]]


class CalendarSyncOut(BaseModel):
    connected: bool
    changed: bool = False
    created: int = 0
    updated: int = 0
    deleted: int = 0
    pulled: int = 0
    conflicts: list[CalendarConflictOut] = []
    error: Optional[str] = None
    needs_reauth: bool = False
    events: list[CalendarEventOut] = []


# ---------- Multiple Gmail accounts ----------

class GmailAccountOut(BaseModel):
    id: str
    email: str
    label: str = ""
    is_primary: bool = False
    last_synced_at: Optional[datetime] = None


class GmailAccountsOut(BaseModel):
    accounts: list[GmailAccountOut]
    selected: str  # a connection id, or "all"


class GmailAccountConnectIn(BaseModel):
    label: str = Field(default="", max_length=60)


class GmailAccountUpdateIn(BaseModel):
    label: str = Field(max_length=60)


class GmailAccountSelectIn(BaseModel):
    account_id: str  # a connection id, or "all"
