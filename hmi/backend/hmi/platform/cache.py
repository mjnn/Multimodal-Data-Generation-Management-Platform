"""Product cache key: hash(input ids + operator + canonical params)."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def product_cache_key(input_ids: list[str], op_id: str, params: dict[str, Any] | None = None) -> str:
    payload = {
        "inputs": sorted(str(i) for i in input_ids),
        "op": str(op_id),
        "params": params or {},
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
