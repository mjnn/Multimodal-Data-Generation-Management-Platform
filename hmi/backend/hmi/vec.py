"""In-memory cosine similarity for embedding search (demo scale)."""

from __future__ import annotations

import json
from typing import Any

import numpy as np


def parse_embedding(raw: str | None) -> np.ndarray | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
        if isinstance(data, list) and data:
            return np.asarray(data, dtype=np.float32)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    return None


def cos_sim(a: np.ndarray, b: np.ndarray) -> float:
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


def similar_filtered(
    query_vec: np.ndarray,
    candidates: list[dict[str, Any]],
    *,
    min_score: float = 0.75,
    top_k: int = 8,
) -> list[tuple[dict[str, Any], float]]:
    scored: list[tuple[dict[str, Any], float]] = []
    for item in candidates:
        vec = item.get("_vec")
        if vec is None or vec.shape != query_vec.shape:
            continue
        score = cos_sim(query_vec, vec)
        if score >= min_score:
            scored.append((item, score))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]
