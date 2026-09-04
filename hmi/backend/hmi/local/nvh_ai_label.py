"""阵列 NVH 的 L6 语义字段填充（nvh.sem.*）。

不改动客观 deriver 叶子。按 version_code 绑定 draft ``audio_nvh-v2``，
**禁止**调用会 archive OMS 的全局 ``publish_version``。

配方 ``stages.label.model``：
- ``nvh_sem_heuristic``：由 L2 客观指标离线规则
- ``nvh_sem_ast``：YuanGongND AST + AudioSet-527，top-k → category/sources
- ``nvh_sem_vl``：可选百炼 VL 看 mel.png，失败回退 heuristic
"""

from __future__ import annotations

import json
import logging
import os
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hmi.platform.audio_nvh_v2 import VERSION_CODE

logger = logging.getLogger(__name__)

AI_LABEL_VERSION = "nvh_ai_label-v1"
DEFAULT_MODEL = "nvh_sem_heuristic"
AST_MODEL = "nvh_sem_ast"

# AI may write these; never invent objective metrics.
SEMANTIC_KEYS = frozenset(
    {
        "nvh.sem.noise_category",
        "nvh.sem.noise_sources",
        "nvh.sem.tonal_annoyance",
        "nvh.sem.broadband_annoyance",
        "nvh.sem.quality_grade",
        "nvh.sem.spec_compliance",
        "nvh.sem.spec_limit_db",
        "nvh.sem.test_point",
        "nvh.sem.annotator_notes",
        "nvh.sem.ai_hypothesis",
    }
)

# Prefixes that must never be overwritten by semantic AI.
OBJECTIVE_PREFIXES = (
    "nvh.clip.",
    "nvh.ch.",
    "nvh.band.",
    "nvh.time.",
    "nvh.spatial.",
    "nvh.meta.",
)

NOISE_CATEGORY_VALUES = frozenset(
    {
        "powertrain",
        "engine",
        "motor",
        "transmission",
        "road",
        "wind",
        "brake",
        "hvac",
        "electrical",
        "structure",
        "impulse",
        "tonal",
        "broadband",
        "speech",
        "media",
        "unknown",
    }
)
ANNOYANCE_VALUES = frozenset({"none", "low", "medium", "high"})
QUALITY_VALUES = frozenset({"A", "B", "C", "D"})
SPEC_VALUES = frozenset({"pass", "fail", "marginal", "na"})


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def is_objective_key(key: str) -> bool:
    if key.startswith("_"):
        return False
    return any(key.startswith(p) for p in OBJECTIVE_PREFIXES)


def resolve_audio_nvh_taxonomy_version_id() -> str | None:
    """Draft or published ``audio_nvh-v2`` id — never publishes."""
    try:
        from hmi.taxonomy_db import get_version_by_code

        ver = get_version_by_code(VERSION_CODE)
    except Exception as exc:  # noqa: BLE001
        logger.warning("resolve audio_nvh taxonomy failed: %s", exc)
        return None
    if not ver:
        return None
    status = str(ver.get("status") or "")
    if status not in {"draft", "published"}:
        return None
    return str(ver["id"])


def merge_nvh_semantic_labels(
    base: dict[str, Any],
    semantic: dict[str, Any],
) -> dict[str, Any]:
    """Merge semantic patch into labels; never clobber objective / unknown keys."""
    out = deepcopy(base)
    applied: dict[str, Any] = {}
    for key, val in semantic.items():
        if key.startswith("_"):
            continue
        if key not in SEMANTIC_KEYS:
            continue
        if is_objective_key(key):
            continue
        out[key] = val
        applied[key] = val
    meta = dict(out.get("_meta") or {})
    meta["taxonomy_version_code"] = VERSION_CODE
    meta["ai_label_version"] = AI_LABEL_VERSION
    meta["ai_labeled_at"] = _utc_now_iso()
    meta["ai_semantic_keys"] = sorted(applied.keys())
    # Preserve deriver provenance; annotate dual source.
    src = str(meta.get("label_source") or "")
    if "derive" in src and "ai" not in src:
        meta["label_source"] = "derive_nvh_labels+nvh_ai_label"
    elif not src:
        meta["label_source"] = "nvh_ai_label"
    out["_meta"] = meta
    return out


def _load_tonal_components(run_root: Path, labels: dict[str, Any]) -> list[dict[str, Any]]:
    ref = labels.get("nvh.band.tonal_components")
    rel = None
    if isinstance(ref, dict):
        rel = ref.get("_ref")
    path = run_root / str(rel) if rel else run_root / "audio_spec" / "derived" / "tonal_components.json"
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []
    return data if isinstance(data, list) else []


def heuristic_nvh_semantic(
    labels: dict[str, Any],
    *,
    run_root: Path | None = None,
) -> dict[str, Any]:
    """Deterministic L6 fill from objective metrics (offline / stub)."""
    leq = float(labels.get("nvh.clip.spl.leq_db_mean") or 0.0)
    level = str(labels.get("nvh.clip.spl.level_class") or "unknown")
    tonality = float(labels.get("nvh.clip.spec.tonality_index") or 0.0)
    peak_db = float(labels.get("nvh.clip.spl.peak_db_max") or leq)
    crest = peak_db - leq

    tonal_rows: list[dict[str, Any]] = []
    if run_root is not None:
        tonal_rows = _load_tonal_components(run_root, labels)
    max_prom = 0.0
    for row in tonal_rows:
        try:
            max_prom = max(max_prom, float(row.get("prominence_db") or 0.0))
        except (TypeError, ValueError):
            continue

    if tonality >= 0.35 or max_prom >= 6.0:
        category = "tonal"
        sources = ["other"]
        tonal_ann = "high" if max_prom >= 10.0 or tonality >= 0.5 else "medium"
        bb_ann = "low"
    elif crest >= 12.0:
        category = "impulse"
        sources = ["other"]
        tonal_ann = "low"
        bb_ann = "medium"
    elif leq >= 85.0:
        category = "broadband"
        sources = ["road_texture"] if leq < 100.0 else ["other"]
        tonal_ann = "none"
        bb_ann = "high" if leq >= 95.0 else "medium"
    else:
        category = "unknown"
        sources = ["other"]
        tonal_ann = "none"
        bb_ann = "low" if leq >= 70.0 else "none"

    if level == "low":
        quality = "A"
    elif level == "medium":
        quality = "B"
    elif level == "high":
        quality = "C"
    else:
        quality = "D"

    hypothesis = (
        f"heuristic:{AI_LABEL_VERSION} leq={leq:.1f}dB level={level} "
        f"tonality={tonality:.3f} max_prom={max_prom:.1f}dB crest={crest:.1f}dB "
        f"→ category={category} quality={quality}"
    )
    return {
        "nvh.sem.noise_category": category,
        "nvh.sem.noise_sources": sources,
        "nvh.sem.tonal_annoyance": tonal_ann,
        "nvh.sem.broadband_annoyance": bb_ann,
        "nvh.sem.quality_grade": quality,
        "nvh.sem.spec_compliance": "na",
        "nvh.sem.ai_hypothesis": hypothesis,
    }


def _sanitize_vl_payload(raw: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    cat = raw.get("nvh.sem.noise_category") or raw.get("noise_category")
    if isinstance(cat, str) and cat.strip() in NOISE_CATEGORY_VALUES:
        out["nvh.sem.noise_category"] = cat.strip()
    sources = raw.get("nvh.sem.noise_sources") or raw.get("noise_sources")
    if isinstance(sources, list):
        cleaned = [str(s).strip() for s in sources if str(s).strip()]
        if cleaned:
            out["nvh.sem.noise_sources"] = cleaned
    for key, allowed in (
        ("nvh.sem.tonal_annoyance", ANNOYANCE_VALUES),
        ("nvh.sem.broadband_annoyance", ANNOYANCE_VALUES),
        ("nvh.sem.quality_grade", QUALITY_VALUES),
        ("nvh.sem.spec_compliance", SPEC_VALUES),
    ):
        short = key.rsplit(".", 1)[-1]
        val = raw.get(key) or raw.get(short)
        if isinstance(val, str) and val.strip() in allowed:
            out[key] = val.strip()
    for key in ("nvh.sem.spec_limit_db", "nvh.sem.test_point", "nvh.sem.annotator_notes", "nvh.sem.ai_hypothesis"):
        short = key.rsplit(".", 1)[-1]
        val = raw.get(key) if key in raw else raw.get(short)
        if val is None:
            continue
        if key == "nvh.sem.spec_limit_db":
            try:
                out[key] = float(val)
            except (TypeError, ValueError):
                pass
        elif isinstance(val, str) and val.strip():
            out[key] = val.strip()
    return out


def _find_mel_png(run_root: Path) -> Path | None:
    for ch in ("VL", "VR", "HL", "HR"):
        p = run_root / "audio_spec" / ch / "mel.png"
        if p.is_file():
            return p
    matches = sorted((run_root / "audio_spec").glob("*/mel.png")) if (run_root / "audio_spec").is_dir() else []
    return matches[0] if matches else None


def vl_nvh_semantic(run_root: Path, labels: dict[str, Any], *, model: str) -> dict[str, Any] | None:
    """Optional VL fill via DashScope or AIGW OpenAI-compatible chat; None when unavailable."""
    mel = _find_mel_png(run_root)
    if mel is None:
        logger.info("nvh_sem_vl skipped: no mel.png under %s", run_root)
        return None

    leq = labels.get("nvh.clip.spl.leq_db_mean")
    tonality = labels.get("nvh.clip.spec.tonality_index")
    prompt = (
        "You are an NVH acoustics assistant. Given a mel spectrogram of a 4-ch cabin mic array "
        "and objective metrics, fill ONLY semantic JSON keys. "
        f"Objective: leq_db_mean={leq}, tonality_index={tonality}. "
        "Return a single JSON object with keys: noise_category "
        "(one of powertrain/road/wind/brake/hvac/electrical/structure/impulse/tonal/broadband/"
        "speech/media/unknown), noise_sources (string array), tonal_annoyance, broadband_annoyance "
        "(none|low|medium|high), quality_grade (A|B|C|D), spec_compliance (pass|fail|marginal|na), "
        "ai_hypothesis (short Chinese or English rationale). "
        "Do NOT invent SPL numbers. JSON only."
    )
    vl_model = model if model and model != "nvh_sem_vl" else (
        os.getenv("HMI_NVH_VL_MODEL") or "qwen-vl-plus"
    ).strip()

    provider = (os.getenv("OMNI_PROVIDER") or os.getenv("LLM_PROVIDER") or "dashscope").strip().lower()
    text = ""
    if provider in {"aigw", "openai", "openai_compat", "gateway"}:
        try:
            from oms_multimodal.llm_provider import load_aigw_settings, make_openai_client
        except ImportError:
            logger.warning("nvh_sem_vl aigw skipped: oms_multimodal not importable")
            return None
        try:
            aigw = load_aigw_settings()
            client = make_openai_client(
                base_url=aigw.base_url, api_key=aigw.api_key, timeout_sec=aigw.timeout_sec
            )
            use_model = (aigw.omni_model or vl_model).strip()
            import base64

            b64 = base64.b64encode(mel.read_bytes()).decode("utf-8")
            data_uri = f"data:image/png;base64,{b64}"
            completion = client.chat.completions.create(
                model=use_model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": data_uri}},
                            {"type": "text", "text": prompt},
                        ],
                    }
                ],
                stream=False,
            )
            content = completion.choices[0].message.content if completion.choices else ""
            text = str(content or "").strip()
        except Exception as exc:  # noqa: BLE001
            logger.warning("nvh_sem_vl aigw call failed: %s", exc)
            return None
    else:
        api_key = (os.getenv("DASHSCOPE_API_KEY") or "").strip()
        if not api_key:
            logger.info("nvh_sem_vl skipped: DASHSCOPE_API_KEY unset")
            return None
        try:
            import dashscope
            from dashscope import MultiModalConversation
        except ImportError:
            logger.warning("nvh_sem_vl skipped: dashscope not installed")
            return None
        dashscope.api_key = api_key
        try:
            resp = MultiModalConversation.call(
                model=vl_model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"image": str(mel.resolve())},
                            {"text": prompt},
                        ],
                    }
                ],
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("nvh_sem_vl call failed: %s", exc)
            return None

        try:
            text = resp["output"]["choices"][0]["message"]["content"][0]["text"]
        except Exception:  # noqa: BLE001
            try:
                content = resp["output"]["choices"][0]["message"]["content"]
                if isinstance(content, str):
                    text = content
                elif isinstance(content, list):
                    text = " ".join(
                        str(x.get("text") or "") for x in content if isinstance(x, dict)
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning("nvh_sem_vl parse failed: %s", exc)
                return None
        text = (text or "").strip()

    if not text:
        return None
    # Strip markdown fences if present
    if "```" in text:
        parts = text.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("{"):
                text = part
                break
    try:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return None
        raw = json.loads(text[start : end + 1])
    except Exception as exc:  # noqa: BLE001
        logger.warning("nvh_sem_vl JSON failed: %s", exc)
        return None
    if not isinstance(raw, dict):
        return None
    cleaned = _sanitize_vl_payload(raw)
    if not cleaned.get("nvh.sem.ai_hypothesis"):
        cleaned["nvh.sem.ai_hypothesis"] = f"vl:{vl_model} {json.dumps(cleaned, ensure_ascii=False)[:400]}"
    return cleaned if cleaned else None


def infer_audioset_probs(run_root: Path, labels: dict[str, Any]) -> list[float] | None:
    """Return 527 AudioSet sigmoid probs, or None when AST is unavailable."""
    try:
        from hmi.local.nvh_ast.infer import infer_audioset_probs as _infer

        return _infer(run_root, labels)
    except Exception as exc:  # noqa: BLE001
        logger.info("nvh_sem_ast infer skipped: %s", exc)
        return None


def _semantic_from_ast(
    run_root: Path,
    labels: dict[str, Any],
    _model_name: str,
) -> tuple[dict[str, Any], str]:
    heuristic = heuristic_nvh_semantic(labels, run_root=run_root)
    probs = infer_audioset_probs(run_root, labels)
    if not probs:
        return heuristic, "heuristic_fallback"
    from hmi.local.nvh_ast.labels import format_ast_hypothesis, map_audioset_topk

    mapped = map_audioset_topk(probs)
    semantic = dict(heuristic)
    if mapped.get("mapped") and mapped.get("noise_category"):
        semantic["nvh.sem.noise_category"] = mapped["noise_category"]
    if mapped.get("noise_sources"):
        semantic["nvh.sem.noise_sources"] = list(mapped["noise_sources"])
    leq = labels.get("nvh.clip.spl.leq_db_mean")
    try:
        leq_f = float(leq) if leq is not None else None
    except (TypeError, ValueError):
        leq_f = None
    semantic["nvh.sem.ai_hypothesis"] = format_ast_hypothesis(
        mapped,
        heuristic_leq=leq_f,
        heuristic_quality=str(heuristic.get("nvh.sem.quality_grade") or ""),
    )
    return semantic, "ast"


def fill_nvh_semantic_labels(
    run_root: Path,
    labels: dict[str, Any],
    *,
    model: str | None = None,
) -> dict[str, Any]:
    """After deriver: fill nvh.sem.* without touching objective leaves."""
    model_name = (model or DEFAULT_MODEL).strip() or DEFAULT_MODEL
    semantic: dict[str, Any] = {}
    used = "heuristic"

    if model_name.startswith("nvh_sem_vl") or model_name in {"qwen-vl-plus", "qwen3-vl-plus"}:
        vl = vl_nvh_semantic(run_root, labels, model=model_name)
        if vl:
            semantic = vl
            used = "vl"
        else:
            semantic = heuristic_nvh_semantic(labels, run_root=run_root)
            used = "heuristic_fallback"
    elif model_name == AST_MODEL or model_name.startswith("nvh_sem_ast"):
        semantic, used = _semantic_from_ast(run_root, labels, model_name)
    else:
        semantic = heuristic_nvh_semantic(labels, run_root=run_root)
        used = "heuristic"

    # Snapshot objective keys for integrity
    objective_snap = {k: deepcopy(v) for k, v in labels.items() if is_objective_key(k)}
    merged = merge_nvh_semantic_labels(labels, semantic)
    for k, v in objective_snap.items():
        if merged.get(k) != v:
            raise RuntimeError(f"nvh_ai_label clobbered objective key {k}")
    meta = dict(merged.get("_meta") or {})
    meta["ai_model"] = model_name
    meta["ai_mode"] = used
    merged["_meta"] = meta
    return merged
