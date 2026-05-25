from __future__ import annotations

import os
from dataclasses import dataclass

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None


@dataclass(frozen=True)
class Settings:
    x_bearer_token: str | None
    x_username: str
    notion_token: str | None
    notion_database_id: str | None
    google_service_account_json: str | None
    google_sheet_id: str | None
    google_worksheet_name: str
    state_db: str
    mock_posts: str | None
    max_results: int
    dry_run: bool
    no_x_api: bool

    @classmethod
    def from_env(cls, *, env_file: str | None = ".env") -> "Settings":
        if load_dotenv and env_file:
            load_dotenv(env_file)
        return cls(
            x_bearer_token=_blank_to_none(os.getenv("X_BEARER_TOKEN")),
            x_username=os.getenv("X_USERNAME", "info_myojou"),
            notion_token=_blank_to_none(os.getenv("NOTION_TOKEN")),
            notion_database_id=_blank_to_none(os.getenv("NOTION_DATABASE_ID")),
            google_service_account_json=_blank_to_none(os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")),
            google_sheet_id=_blank_to_none(os.getenv("GOOGLE_SHEET_ID")),
            google_worksheet_name=os.getenv("GOOGLE_WORKSHEET_NAME", "Live Schedule"),
            state_db=os.getenv("MYOJOU_STATE_DB", ".state/myojou_sync.sqlite"),
            mock_posts=_blank_to_none(os.getenv("MYOJOU_MOCK_POSTS")),
            max_results=_int_from_env("X_MAX_RESULTS", 10),
            dry_run=_bool_from_env("DRY_RUN", default=True),
            no_x_api=_bool_from_env("NO_X_API", default=False),
        )


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _bool_from_env(key: str, *, default: bool) -> bool:
    value = os.getenv(key)
    if value is None:
        return default
    return value.strip().casefold() in {"1", "true", "yes", "y", "on"}


def _int_from_env(key: str, default: int) -> int:
    value = os.getenv(key)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default
