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
            "my_classes": "JSON NOT NULL DEFAULT '[]'",
        },
        "tasks": {
            "notes": "TEXT NOT NULL DEFAULT ''",
            "snoozed_until": "DATETIME",
            "audience": "VARCHAR NOT NULL DEFAULT 'GENERAL'",
        },
        "email_messages": {
            "audience": "VARCHAR NOT NULL DEFAULT 'GENERAL'",
            "audience_label": "VARCHAR NOT NULL DEFAULT ''",
            "audience_locked": "BOOLEAN NOT NULL DEFAULT 0",
        },
        "scan_runs": {
            "stage": "VARCHAR NOT NULL DEFAULT 'QUEUED'",
            "progress": "INTEGER NOT NULL DEFAULT 0",
            "progress_total": "INTEGER NOT NULL DEFAULT 0",
        },
    }
    with engine.begin() as connection:
        inspector = inspect(connection)
        for table, columns in additions.items():
            if table not in inspector.get_table_names():
                continue
            existing = {column["name"] for column in inspector.get_columns(table)}
            for name, definition in columns.items():
                if name not in existing:
                    connection.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {definition}'))
