"""ODPS client helpers for cloud jobs."""

from __future__ import annotations

from odps import ODPS


def create_odps_client(settings: dict[str, str]) -> ODPS:
    return ODPS(
        settings["odps_access_id"],
        settings["odps_access_key"],
        project=settings["odps_project"],
        endpoint=settings["odps_endpoint"],
    )
