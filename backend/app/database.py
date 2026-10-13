from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from app.config import get_settings

settings = get_settings()

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def migrate_sqlite_schema():
    """Add MVP columns without requiring a migration tool for local SQLite."""
    if not settings.database_url.startswith("sqlite"):
        return
    additions = {
        "users": {
            "default_scan_days": "INTEGER NOT NULL DEFAULT 30",
            "notify_scan_completion": "BOOLEAN NOT NULL DEFAULT 1",
            "vip_senders": "JSON NOT NULL DEFAULT '[]'",
            "ignored_senders": "JSON NOT NULL DEFAULT '[]'",
            "selected_gmail_account": "VARCHAR",
        },
        "tasks": {
            "notes": "TEXT NOT NULL DEFAULT ''",
            "snoozed_until": "DATETIME",
            "calendar_event_id": "VARCHAR",
            "calendar_etag": "VARCHAR",
            "calendar_hash": "VARCHAR",
            "calendar_synced_at": "DATETIME",
        },
        "scan_runs": {
            "stage": "VARCHAR NOT NULL DEFAULT 'QUEUED'",
            "progress": "INTEGER NOT NULL DEFAULT 0",
            "progress_total": "INTEGER NOT NULL DEFAULT 0",
            "connection_id": "VARCHAR",
        },
        "gmail_connections": {
            "label": "VARCHAR NOT NULL DEFAULT ''",
            "is_primary": "BOOLEAN NOT NULL DEFAULT 0",
            "google_subject_id": "VARCHAR",
        },
        "email_messages": {
            "connection_id": "VARCHAR",
            "account_email": "VARCHAR NOT NULL DEFAULT ''",
        },
    }
    added: set[tuple[str, str]] = set()
    with engine.begin() as connection:
        inspector = inspect(connection)
        for table, columns in additions.items():
            if table not in inspector.get_table_names():
                continue
            existing = {column["name"] for column in inspector.get_columns(table)}
            for name, definition in columns.items():
                if name not in existing:
                    connection.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {definition}'))
                    added.add((table, name))
        _backfill_multi_account(connection, added)
        for index, table, column in (
            ("ix_tasks_calendar_event_id", "tasks", "calendar_event_id"),
            ("ix_gmail_connections_google_subject_id", "gmail_connections", "google_subject_id"),
            ("ix_email_messages_connection_id", "email_messages", "connection_id"),
            ("ix_scan_runs_connection_id", "scan_runs", "connection_id"),
        ):
            if table in inspector.get_table_names():
                connection.execute(text(f'CREATE INDEX IF NOT EXISTS "{index}" ON "{table}" ("{column}")'))


def _backfill_multi_account(connection, added: set[tuple[str, str]]) -> None:
    """Attach pre-existing single-account data to that account.

    Runs only in the same transaction that adds each column, so it can never
    overwrite later rows that intentionally have no account (all-accounts scans).
    """
    if ("gmail_connections", "google_subject_id") in added:
        connection.execute(text(
            "UPDATE gmail_connections SET google_subject_id = "
            "(SELECT u.google_subject_id FROM users u WHERE u.id = gmail_connections.user_id)"
        ))
    if ("gmail_connections", "is_primary") in added:
        # The pre-existing connection is the account the user signed in with.
        connection.execute(text(
            "UPDATE gmail_connections SET is_primary = 1 WHERE id IN ("
            "  SELECT g.id FROM gmail_connections g WHERE g.created_at = "
            "  (SELECT MIN(x.created_at) FROM gmail_connections x WHERE x.user_id = g.user_id))"
        ))
    primary = "SELECT g.{col} FROM gmail_connections g WHERE g.user_id = {table}.user_id AND g.is_primary = 1"
    if ("email_messages", "connection_id") in added:
        connection.execute(text(
            "UPDATE email_messages SET connection_id = (" + primary.format(col="id", table="email_messages") + "), "
            "account_email = COALESCE((" + primary.format(col="google_account_email", table="email_messages") + "), '')"
        ))
    if ("scan_runs", "connection_id") in added:
        connection.execute(text(
            "UPDATE scan_runs SET connection_id = (" + primary.format(col="id", table="scan_runs") + ")"
        ))
