"""Which connected Gmail account(s) the Gmail section is looking at.

A user can connect several Google accounts (School, Personal, Work, ...). The
selection is stored on the user so every Gmail view and action (scans, scan
history, email search, the assistant's email search) agrees on it.
"""
from __future__ import annotations

from app.models import GmailConnection, User

ALL = "all"


def selected_account_id(user: User) -> str:
    """The selected connection's id, or "all". A stale selection falls back to "all"."""
    chosen = user.selected_gmail_account
    if chosen and chosen != ALL and any(c.id == chosen for c in user.gmail_connections):
        return chosen
    return ALL


def scope_connections(user: User, account_id: str | None = None) -> list[GmailConnection]:
    """Connections for an explicit account_id ("all" or an id), else the selection."""
    wanted = account_id or selected_account_id(user)
    if wanted == ALL:
        return list(user.gmail_connections)
    return [c for c in user.gmail_connections if c.id == wanted]


def find_account(user: User, reference: str) -> GmailConnection | None:
    """Look an account up by id, label or email address (case-insensitive)."""
    needle = (reference or "").strip().lower()
    if not needle:
        return None
    for connection in user.gmail_connections:
        if needle in (connection.id.lower(), (connection.label or "").lower(), connection.google_account_email.lower()):
            return connection
    return None


def display_name(connection: GmailConnection) -> str:
    return connection.label or connection.google_account_email
