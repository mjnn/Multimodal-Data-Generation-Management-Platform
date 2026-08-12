"""Shared helpers for overview clip query (label filters + scene semantic search)."""

from __future__ import annotations

import os
import re
from typing import Any

import numpy as np

from hmi.labels_util import extract_scene_description, labels_preview, match_label_filters, parse_labels_json
from hmi.vec import cos_sim, parse_embedding

_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]|[a-zA-Z0-9_]+")

# Semantic filter policy (overview clip search):
# - Text floor: lexical overlap must be meaningful (not a stray char).
# - Embed floor: cosine vs clip vectors; well below find_similar(0.75) so NL
#   queries still hit, but high enough that weak positive sims are dropped.
# - Relative cutoff: after absolute floors, keep scores within band of the best
#   hit so a long tail of barely-above-threshold clips is not returned.
# - Flat-band guard: if survivors are many and nearly identical mid scores,
#   treat as "no discriminative signal" → empty (avoids returning the corpus).
DEFAULT_MIN_TEXT_SCORE = 0.25
DEFAULT_MIN_EMBED_SCORE = 0.40
DEFAULT_RELATIVE_CUTOFF = 0.85
DEFAULT_FLAT_BEST_MAX = 0.55
DEFAULT_FLAT_SPREAD_MAX = 0.06
DEFAULT_FLAT_MIN_COUNT = 2


def normalize_label_filters(raw: Any) -> dict[str, Any] | None:
    if raw is None or raw == "" or raw == {}:
        return None
    if isinstance(raw, str):
        import json

        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return None
    if not isinstance(raw, dict):
        return None
    out: dict[str, Any] = {}
    for key, value in raw.items():
        lid = str(key).strip()
        if not lid or value is None or value == "":
            continue
        if isinstance(value, (list, tuple)):
            cleaned = [v for v in value if v is not None and v != ""]
            if cleaned:
                out[lid] = cleaned
            continue
        if isinstance(value, dict):
            cleaned_dict: dict[str, Any] = {}
            if "in" in value:
                inn = value.get("in")
                if isinstance(inn, (list, tuple)):
                    opts = [v for v in inn if v is not None and v != ""]
                    if opts:
                        cleaned_dict["in"] = list(opts)
                elif inn is not None and inn != "":
                    cleaned_dict["in"] = [inn]
            if "eq" in value and value.get("eq") is not None and value.get("eq") != "":
                cleaned_dict["eq"] = value.get("eq")
            for rk in ("min", "max"):
                if value.get(rk) is not None and value.get(rk) != "":
                    cleaned_dict[rk] = value.get(rk)
            if cleaned_dict:
                out[lid] = cleaned_dict
            continue
        out[lid] = value
    return out or None


def tokenize_for_relevance(text: str) -> list[str]:
    raw = (text or "").strip().lower()
    if not raw:
        return []
    return [t for t in _TOKEN_RE.findall(raw) if t]


def text_relevance_score(query: str, document: str) -> float:
    """Lightweight lexical relevance in [0, 1] for Chinese/English scene text."""
    q = (query or "").strip().lower()
    doc = (document or "").strip().lower()
    if not q or not doc:
        return 0.0
    if q in doc:
        # Prefer longer relative match
        return min(1.0, 0.72 + 0.28 * (len(q) / max(len(doc), 1)))
    q_tokens = tokenize_for_relevance(q)
    if not q_tokens:
        return 0.0
    doc_tokens = set(tokenize_for_relevance(doc))
    if not doc_tokens:
        return 0.0
    hit = sum(1 for t in q_tokens if t in doc_tokens or t in doc)
    ratio = hit / len(q_tokens)
    # Soft credit for contiguous bigrams of CJK chars
    bigram_bonus = 0.0
    cjk = [t for t in q_tokens if len(t) == 1 and "\u4e00" <= t <= "\u9fff"]
    if len(cjk) >= 2:
        bigrams = [cjk[i] + cjk[i + 1] for i in range(len(cjk) - 1)]
        bigram_hit = sum(1 for b in bigrams if b in doc)
        bigram_bonus = 0.15 * (bigram_hit / len(bigrams))
    return min(1.0, ratio * 0.85 + bigram_bonus)


def scene_text_for_clip(
    labels_json: dict[str, Any] | None,
    *,
    scene_summary: str | None = None,
) -> str:
    return extract_scene_description(labels_json, scene_summary=scene_summary)


def try_embed_query_text(query: str, *, dimension: int | None = None) -> np.ndarray | None:
    """Embed NL query with qwen3-vl-embedding (text-only). Returns None if unavailable."""
    text = (query or "").strip()
    if not text:
        return None
    api_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        from http import HTTPStatus

        from dashscope import MultiModalEmbedding
    except Exception:
        return None
    model = os.getenv("HMI_SEMANTIC_EMBED_MODEL", "qwen3-vl-embedding").strip() or "qwen3-vl-embedding"
    dim = dimension
    if dim is None:
        try:
            dim = int(os.getenv("HMI_SEMANTIC_EMBED_DIM", "1024") or "1024")
        except ValueError:
            dim = 1024
    try:
        resp = MultiModalEmbedding.call(
            api_key=api_key,
            model=model,
            input=[{"text": text}],
            enable_fusion=True,
            dimension=dim,
        )
        if getattr(resp, "status_code", None) != HTTPStatus.OK:
            return None
        embeddings = (getattr(resp, "output", None) or {}).get("embeddings") or []
        if not embeddings:
            return None
        vec = embeddings[0].get("embedding")
        if not isinstance(vec, list) or not vec:
            return None
        return np.asarray(vec, dtype=np.float32)
    except Exception:
        return None


def score_clip_candidate(
    *,
    labels_json: dict[str, Any] | None,
    scene_summary: str | None,
    vector_json: str | None,
    label_filters: dict[str, Any] | None,
    semantic_query: str,
    query_vec: np.ndarray | None,
    min_semantic_score: float,
    min_embed_score: float = DEFAULT_MIN_EMBED_SCORE,
) -> dict[str, Any] | None:
    """Return scored hit dict or None if filtered out.

    Semantic pass rule (when query non-empty): keep if text_score >= text floor
    OR embed_score >= embed floor. Weak positive cosine alone must not pass.
    """
    parsed = labels_json if isinstance(labels_json, dict) else parse_labels_json(labels_json)
    if label_filters and not match_label_filters(parsed, label_filters):
        return None

    scene = scene_text_for_clip(parsed, scene_summary=scene_summary)
    preview = labels_preview(parsed) if parsed else ""
    q = (semantic_query or "").strip()
    if not q:
        return {
            "score": 1.0,
            "match_mode": "label",
            "scene_description": scene,
            "label_preview": preview,
        }

    text_floor = float(min_semantic_score) if min_semantic_score is not None else DEFAULT_MIN_TEXT_SCORE
    text_floor = max(0.0, min(text_floor, 1.0))
    embed_floor = float(min_embed_score) if min_embed_score is not None else DEFAULT_MIN_EMBED_SCORE
    embed_floor = max(0.0, min(embed_floor, 1.0))

    text_score = text_relevance_score(q, scene)
    if preview and preview != scene:
        text_score = max(text_score, text_relevance_score(q, preview) * 0.92)

    embed_score = 0.0
    if query_vec is not None and vector_json:
        vec = parse_embedding(str(vector_json))
        if vec is not None and vec.shape == query_vec.shape:
            embed_score = float(cos_sim(query_vec, vec))

    text_ok = text_score >= text_floor
    embed_ok = embed_score >= embed_floor
    if not text_ok and not embed_ok:
        return None

    if embed_ok and text_ok:
        score = 0.65 * embed_score + 0.35 * text_score
        mode = "hybrid"
    elif embed_ok:
        score = embed_score
        mode = "embedding"
    else:
        score = text_score
        mode = "text"

    return {
        "score": round(score, 4),
        "match_mode": mode,
        "scene_description": scene,
        "label_preview": preview,
        "text_score": round(text_score, 4),
        "embedding_score": round(embed_score, 4) if embed_score else None,
    }


def apply_semantic_rank_cutoff(
    items: list[dict[str, Any]],
    *,
    relative_cutoff: float = DEFAULT_RELATIVE_CUTOFF,
    top_k: int = 200,
    reject_flat_band: bool = True,
) -> list[dict[str, Any]]:
    """Drop the long tail relative to the best score, then apply top_k.

    Absolute floors are applied in score_clip_candidate; this only tightens
    ranking when a clear best match exists among survivors.
    """
    if not items:
        return []
    rel = max(0.0, min(float(relative_cutoff), 1.0))
    best = max(float(i.get("score") or 0.0) for i in items)
    floor = best * rel
    kept = [i for i in items if float(i.get("score") or 0.0) >= floor]
    if (
        reject_flat_band
        and len(kept) >= DEFAULT_FLAT_MIN_COUNT
        and best < DEFAULT_FLAT_BEST_MAX
    ):
        worst = min(float(i.get("score") or 0.0) for i in kept)
        if (best - worst) <= DEFAULT_FLAT_SPREAD_MAX:
            # Uniform mid-range similarity → not a real filter signal.
            return []
    kept.sort(key=lambda r: (-float(r.get("score") or 0), str(r.get("clip_id") or "")))
    return kept[: max(1, min(int(top_k), 500))]
