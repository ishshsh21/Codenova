"""Read-only client for Google's hosted Gmail MCP server.

The user's encrypted OAuth refresh token is exchanged for a short-lived access
token for each request. Refresh tokens and email contents are never logged.
"""
from __future__ import annotations

import json
from typing import Any

import httpx
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from app.config import get_settings


class GmailMcpError(RuntimeError):
    """Raised when the hosted Gmail MCP server cannot complete a request."""


class GmailMcpClient:
    """Minimal JSON-RPC client for the official Gmail MCP HTTP endpoint."""

    def __init__(self, refresh_token: str):
        self._refresh_token = refresh_token
        self._settings = get_settings()

    def search_threads(self, query: str, page_size: int = 10) -> dict[str, Any]:
        return self._call_tool(
            "search_threads",
            {
                "query": query[:500],
                "pageSize": max(1, min(page_size, 10)),
                "includeTrash": False,
                "view": "THREAD_VIEW_MINIMAL",
            },
        )

    def get_thread(self, thread_id: str) -> dict[str, Any]:
        return self._call_tool(
            "get_thread",
            {"threadId": thread_id[:200], "messageFormat": "FULL_CONTENT"},
        )

    def _access_token(self) -> str:
        try:
            credentials = Credentials(
                token=None,
                refresh_token=self._refresh_token,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=self._settings.google_client_id,
                client_secret=self._settings.google_client_secret,
                scopes=self._settings.gmail_scopes,
            )
            credentials.refresh(Request())
            if not credentials.token:
                raise GmailMcpError("Could not refresh the Gmail access token")
            return credentials.token
        except GmailMcpError:
            raise
        except Exception as exc:
            raise GmailMcpError("Could not refresh the Gmail access token") from exc

    def _call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        # The endpoint documents direct JSON-RPC calls to tools/call. Keeping
        # this allowlist in the caller ensures the chatbot never receives a
        # write-capable Gmail MCP tool.
        request_body = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
        try:
            response = httpx.post(
                self._settings.gmail_mcp_endpoint,
                headers={
                    "Authorization": f"Bearer {self._access_token()}",
                    "Accept": "application/json, text/event-stream",
                    "Content-Type": "application/json",
                },
                json=request_body,
                timeout=30.0,
            )
            response.raise_for_status()
            payload = _decode_mcp_response(response)
        except (httpx.HTTPError, ValueError) as exc:
            raise GmailMcpError("Gmail MCP request failed") from exc

        if payload.get("error"):
            raise GmailMcpError(_safe_mcp_error(payload["error"], response.reason_phrase))
        result = payload.get("result")
        if not isinstance(result, dict) or result.get("isError"):
            raise GmailMcpError(_safe_mcp_error(result, response.reason_phrase))
        return result


def _decode_mcp_response(response: httpx.Response) -> dict[str, Any]:
    """Return the JSON-RPC payload from JSON or Streamable-HTTP/SSE output."""
    content_type = response.headers.get("content-type", "")
    if "application/json" in content_type:
        return response.json()

    payloads = [
        json.loads(line.removeprefix("data:").strip())
        for line in response.text.splitlines()
        if line.startswith("data:") and line.removeprefix("data:").strip()
    ]
    if not payloads:
        raise ValueError("Gmail MCP returned an empty response")
    return payloads[-1]


def _safe_mcp_error(payload: Any, reason_phrase: str = "") -> str:
    """Return a non-sensitive error category without logging MCP content."""
    serialized = f"{reason_phrase} {json.dumps(payload, ensure_ascii=True)}".lower()
    if any(marker in serialized for marker in ("forbidden", "permission", "denied", "access", "403")):
        return "Gmail MCP access was denied. Reconnect Gmail after enabling Gmail MCP API and gmail.readonly."
    if "unauth" in serialized or "401" in serialized or "credential" in serialized:
        return "Gmail MCP authorization expired. Reconnect Gmail and try again."
    return "Gmail MCP could not complete the tool call."
