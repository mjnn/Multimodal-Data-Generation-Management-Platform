"""Route service calls to cloud or local implementation."""

from __future__ import annotations

from hmi.data_source import is_local_mode
from hmi.services import clips, clips_local, search, search_local


def clips_svc():
    return clips_local if is_local_mode() else clips


def search_svc():
    return search_local if is_local_mode() else search
