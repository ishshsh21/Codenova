"""
Centralized app configuration. Values are read from environment variables
(or a local .env file) via pydantic-settings.
"""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App
    app_secret_key: str = "dev-secret-change-me"
    fernet_key: str = ""
    frontend_url: str = "http://localhost:5173"
    database_url: str = "sqlite:///./workday_agent.db"

    # Google OAuth / Gmail
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/api/auth/google/callback"
    gmail_scopes: list[str] = ["https://www.googleapis.com/auth/gmail.readonly"]
    gmail_mcp_endpoint: str = "https://gmailmcp.googleapis.com/mcp/v1"

    # LLM — Gemini API (falls back to a rule-based extractor if unset)
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    assistant_max_output_tokens: int = 1200

    # Sync defaults
    default_sync_query: str = "newer_than:30d"
    max_messages_per_sync: int = 150
    sync_worker_count: int = 8
    # Gmail enforces per-minute quotas per user, so message fetches get fewer
    # parallel workers than the (much less rate-limited) AI extraction step.
    gmail_fetch_workers: int = 4


@lru_cache
def get_settings() -> Settings:
    return Settings()
