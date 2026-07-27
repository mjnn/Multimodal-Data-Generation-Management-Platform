"""Short TTL cache for overview list + batch stats (local / cloud)."""

from __future__ import annotations

from copy import deepcopy
from typing import Callable, TypeVar

from cachetools import TTLCache

OVERVIEW_CACHE_TTL_SEC = 60

T = TypeVar("T")

_light_cache: TTLCache = TTLCache(maxsize=4, ttl=OVERVIEW_CACHE_TTL_SEC)
_stats_cache: TTLCache = TTLCache(maxsize=4, ttl=OVERVIEW_CACHE_TTL_SEC)


def overview_cache_clear() -> None:
    _light_cache.clear()
    _stats_cache.clear()


def cached_overview_list(scope: str, *, refresh: bool, build: Callable[[], list]) -> list:
    if not refresh and scope in _light_cache:
        return deepcopy(_light_cache[scope])
    rows = build()
    _light_cache[scope] = deepcopy(rows)
    return rows


def cached_overview_stats(scope: str, *, refresh: bool, build: Callable[[], dict]) -> dict:
    if not refresh and scope in _stats_cache:
        return deepcopy(_stats_cache[scope])
    stats = build()
    _stats_cache[scope] = deepcopy(stats)
    return stats
