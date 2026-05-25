from __future__ import annotations

from dataclasses import dataclass

from .config import Settings


@dataclass(frozen=True)
class TargetValidation:
    name: str
    required_variables: tuple[str, ...]
    missing_variables: tuple[str, ...]

    @property
    def available(self) -> bool:
        return not self.missing_variables


def validate_targets(settings: Settings) -> list[TargetValidation]:
    return [
        TargetValidation(
            name="notion",
            required_variables=("NOTION_TOKEN", "NOTION_DATABASE_ID"),
            missing_variables=tuple(
                key
                for key, value in (
                    ("NOTION_TOKEN", settings.notion_token),
                    ("NOTION_DATABASE_ID", settings.notion_database_id),
                )
                if not value
            ),
        ),
        TargetValidation(
            name="sheets",
            required_variables=("GOOGLE_SERVICE_ACCOUNT_JSON", "GOOGLE_SHEET_ID"),
            missing_variables=tuple(
                key
                for key, value in (
                    ("GOOGLE_SERVICE_ACCOUNT_JSON", settings.google_service_account_json),
                    ("GOOGLE_SHEET_ID", settings.google_sheet_id),
                )
                if not value
            ),
        ),
        TargetValidation(
            name="x",
            required_variables=("X_BEARER_TOKEN",),
            missing_variables=tuple(["X_BEARER_TOKEN"] if not settings.x_bearer_token else []),
        ),
    ]


def validation_lines(settings: Settings) -> list[str]:
    lines = []
    for target in validate_targets(settings):
        if target.available:
            lines.append(f"{target.name}: available")
        else:
            missing = ", ".join(target.missing_variables)
            lines.append(f"{target.name}: unavailable; missing {missing}")
    lines.append(f"mock_posts: {'available' if settings.mock_posts else 'not configured'}")
    lines.append(f"dry_run: {settings.dry_run}")
    lines.append(f"no_x_api: {settings.no_x_api}")
    return lines


def missing_for_target(settings: Settings, target_name: str) -> tuple[str, ...]:
    for target in validate_targets(settings):
        if target.name == target_name:
            return target.missing_variables
    raise ValueError(f"Unknown validation target: {target_name}")
