"""Application role constants (see PRD §3 + anonymous self-register default)."""

from __future__ import annotations

ROLE_ANONYMOUS = "anonymous"

STANDARD_ROLES = frozenset(
    {
        "admin",
        "reviewer",
        "dataset_manager",
        "model_trainer",
        "pipeline_manager",
    }
)

DEFAULT_REGISTRATION_ROLES = [ROLE_ANONYMOUS]


def normalized_roles(roles: list[str] | None) -> list[str]:
    """Legacy accounts with no rows in app_user_role behave as anonymous."""
    if not roles:
        return [ROLE_ANONYMOUS]
    return roles


def has_standard_role(roles: list[str] | None) -> bool:
    return bool(set(normalized_roles(roles)) & STANDARD_ROLES)
