import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    String, Text, Boolean, Float, Integer, DateTime, Date, ForeignKey, JSON, Enum, UniqueConstraint, Time
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def gen_uuid() -> str:
    return str(uuid.uuid4())


# ---------- Enums (TRD sections 3, 6) ----------

class TaskStatus(str, enum.Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    DISMISSED = "DISMISSED"
    NOT_MY_TASK = "NOT_MY_TASK"


class TaskPriority(str, enum.Enum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


class OwnerType(str, enum.Enum):
    CURRENT_USER = "CURRENT_USER"
    OTHER_PERSON = "OTHER_PERSON"
    TEAM_UNKNOWN = "TEAM_UNKNOWN"


class EmailClassification(str, enum.Enum):
    ACTION_REQUIRED = "ACTION_REQUIRED"
    FYI = "FYI"
    NEWSLETTER = "NEWSLETTER"
    AUTOMATED_NOTIFICATION = "AUTOMATED_NOTIFICATION"
    MEETING_INFORMATION = "MEETING_INFORMATION"
    COMPLETED = "COMPLETED"
    WAITING_FOR_OTHER_PERSON = "WAITING_FOR_OTHER_PERSON"
    FOLLOW_UP_REQUIRED = "FOLLOW_UP_REQUIRED"
    POSSIBLE_TASK = "POSSIBLE_TASK"


class ActionType(str, enum.Enum):
    REPLY = "REPLY"
    REVIEW = "REVIEW"
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    SEND_DOCUMENT = "SEND_DOCUMENT"
    PROVIDE_INFORMATION = "PROVIDE_INFORMATION"
    ATTEND_MEETING = "ATTEND_MEETING"
    CREATE_DOCUMENT = "CREATE_DOCUMENT"
    FIX_ISSUE = "FIX_ISSUE"
    FOLLOW_UP = "FOLLOW_UP"
    READ = "READ"
    DECISION = "DECISION"
    OTHER = "OTHER"


class SourceRelationship(str, enum.Enum):
    ORIGIN = "ORIGIN"
    FOLLOW_UP = "FOLLOW_UP"
    DUPLICATE = "DUPLICATE"


# ---------- Tables (TRD section 6) ----------

class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    google_subject_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    email: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String, default="")
    timezone: Mapped[str] = mapped_column(String, default="Asia/Kolkata")
    workday_start: Mapped[str] = mapped_column(String, default="09:00")
    workday_end: Mapped[str] = mapped_column(String, default="18:00")
    default_scan_days: Mapped[int] = mapped_column(Integer, default=30)
    notify_scan_completion: Mapped[bool] = mapped_column(Boolean, default=True)
    vip_senders: Mapped[list] = mapped_column(JSON, default=list)
    ignored_senders: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    gmail_connection: Mapped["GmailConnection"] = relationship(back_populates="user", uselist=False)


class GmailConnection(Base):
    __tablename__ = "gmail_connections"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"))
    google_account_email: Mapped[str] = mapped_column(String)
    encrypted_refresh_token: Mapped[str] = mapped_column(Text)
    scopes: Mapped[str] = mapped_column(Text, default="")
    watch_history_id: Mapped[str] = mapped_column(String, nullable=True)
    watch_expiration: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    last_synced_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="gmail_connection")


class ScanRun(Base):
    """A persisted Gmail scan and its eventual processing result."""
    __tablename__ = "scan_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String, default="QUEUED", index=True)
    start_date: Mapped[date] = mapped_column(Date, nullable=True)
    end_date: Mapped[date] = mapped_column(Date, nullable=True)
    gmail_query: Mapped[str] = mapped_column(String, default="")
    messages_fetched: Mapped[int] = mapped_column(Integer, default=0)
    messages_processed: Mapped[int] = mapped_column(Integer, default=0)
    tasks_created: Mapped[int] = mapped_column(Integer, default=0)
    tasks_updated: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    stage: Mapped[str] = mapped_column(String, default="QUEUED")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    progress_total: Mapped[int] = mapped_column(Integer, default=0)


class Notification(Base):
    """User-facing events retained for the notification center/history."""
    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), index=True)
    scan_id: Mapped[str] = mapped_column(String, ForeignKey("scan_runs.id"), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String, default="INFO")
    title: Mapped[str] = mapped_column(String)
    message: Mapped[str] = mapped_column(Text)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class EmailThread(Base):
    __tablename__ = "email_threads"
    __table_args__ = (UniqueConstraint("user_id", "gmail_thread_id"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), index=True)
    gmail_thread_id: Mapped[str] = mapped_column(String, index=True)
    subject: Mapped[str] = mapped_column(Text, default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    last_message_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class EmailMessage(Base):
    __tablename__ = "email_messages"
    __table_args__ = (UniqueConstraint("user_id", "gmail_message_id"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), index=True)
    gmail_message_id: Mapped[str] = mapped_column(String, index=True)
    gmail_thread_id: Mapped[str] = mapped_column(String, index=True)
    internal_date: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    sender_email: Mapped[str] = mapped_column(String, default="")
    sender_name: Mapped[str] = mapped_column(String, default="")
    subject: Mapped[str] = mapped_column(Text, default="")
    snippet: Mapped[str] = mapped_column(Text, default="")
    normalized_body: Mapped[str] = mapped_column(Text, default="")
    labels: Mapped[dict] = mapped_column(JSON, default=list)
    has_attachments: Mapped[bool] = mapped_column(Boolean, default=False)

    # Processing / classification (FR-06)
    classification: Mapped[str] = mapped_column(String, nullable=True)
    classification_confidence: Mapped[float] = mapped_column(Float, nullable=True)
    classification_evidence: Mapped[str] = mapped_column(Text, default="")
    processing_status: Mapped[str] = mapped_column(String, default="PENDING")  # PENDING | PROCESSED | FAILED

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String, default=TaskStatus.OPEN.value)
    priority: Mapped[str] = mapped_column(String, default=TaskPriority.P3.value)
    priority_score: Mapped[float] = mapped_column(Float, default=0.0)
    priority_reasons: Mapped[list] = mapped_column(JSON, default=list)

    action_type: Mapped[str] = mapped_column(String, default=ActionType.OTHER.value)
    deadline: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    deadline_raw: Mapped[str] = mapped_column(String, nullable=True)
    deadline_confidence: Mapped[float] = mapped_column(Float, default=0.0)

    owner_type: Mapped[str] = mapped_column(String, default=OwnerType.CURRENT_USER.value)
    owner_label: Mapped[str] = mapped_column(String, default="")

    project: Mapped[str] = mapped_column(String, nullable=True)
    project_confidence: Mapped[float] = mapped_column(Float, default=0.0)

    estimated_effort_minutes: Mapped[int] = mapped_column(Integer, default=30)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    is_blocking: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str] = mapped_column(Text, default="")
    snoozed_until: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)


class TaskSource(Base):
    __tablename__ = "task_sources"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    task_id: Mapped[str] = mapped_column(String, ForeignKey("tasks.id"), index=True)
    message_id: Mapped[str] = mapped_column(String, ForeignKey("email_messages.id"))
    relationship_type: Mapped[str] = mapped_column(String, default=SourceRelationship.ORIGIN.value)


class TaskDependency(Base):
    __tablename__ = "task_dependencies"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    task_id: Mapped[str] = mapped_column(String, ForeignKey("tasks.id"), index=True)
    depends_on_task_id: Mapped[str] = mapped_column(String, ForeignKey("tasks.id"))
    relationship_type: Mapped[str] = mapped_column(String, default="BLOCKS")
    confidence: Mapped[float] = mapped_column(Float, default=0.5)


class TaskFeedback(Base):
    __tablename__ = "task_feedback"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    task_id: Mapped[str] = mapped_column(String, ForeignKey("tasks.id"), index=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"))
    feedback_type: Mapped[str] = mapped_column(String)  # edit | priority | deadline | complete | dismiss | not_my_task | merge | split | project
    old_value: Mapped[dict] = mapped_column(JSON, nullable=True)
    new_value: Mapped[dict] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
