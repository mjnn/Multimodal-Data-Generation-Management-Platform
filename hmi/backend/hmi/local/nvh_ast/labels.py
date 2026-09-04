"""AudioSet-527 names and mapping onto nvh.sem.noise_category / noise_sources."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

_CSV_PATH = Path(__file__).with_name("class_labels_indices.csv")

_CATEGORY_VALUES = frozenset(
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
_SOURCE_VALUES = frozenset(
    {
        "engine",
        "tire",
        "aero",
        "fan",
        "compressor",
        "bearing",
        "panel_rattle",
        "road_texture",
        "exhaust",
        "inverter",
        "other",
    }
)

CATEGORY_BY_NAME: dict[str, str] = {
    "Engine": "engine",
    "Light engine (high frequency)": "engine",
    "Medium engine (mid frequency)": "engine",
    "Heavy engine (low frequency)": "engine",
    "Engine knocking": "engine",
    "Engine starting": "engine",
    "Idling": "engine",
    "Accelerating, revving, vroom": "engine",
    "Traffic noise, roadway noise": "road",
    "Tire squeal": "road",
    "Skidding": "road",
    "Car passing by": "road",
    "Car": "road",
    "Motor vehicle (road)": "road",
    "Truck": "road",
    "Motorcycle": "road",
    "Bus": "road",
    "Wind": "wind",
    "Wind noise (microphone)": "wind",
    "Rustling leaves": "wind",
    "Whoosh, swoosh, swish": "wind",
    "Air brake": "brake",
    "Air conditioning": "hvac",
    "Mechanical fan": "hvac",
    "Hair dryer": "hvac",
    "Mains hum": "electrical",
    "Hum": "electrical",
    "Beep, bleep": "electrical",
    "Buzzer": "electrical",
    "Static": "electrical",
    "Distortion": "electrical",
    "Gears": "structure",
    "Mechanisms": "structure",
    "Creak": "structure",
    "Squeak": "structure",
    "Clatter": "structure",
    "Rattle": "structure",
    "Vibration": "structure",
    "Scratch": "structure",
    "Scrape": "structure",
    "Slam": "impulse",
    "Bang": "impulse",
    "Thump, thud": "impulse",
    "Boom": "impulse",
    "Knock": "impulse",
    "Burst, pop": "impulse",
    "Breaking": "impulse",
    "Shatter": "impulse",
    "Speech": "speech",
    "Male speech, man speaking": "speech",
    "Female speech, woman speaking": "speech",
    "Child speech, kid speaking": "speech",
    "Conversation": "speech",
    "Narration, monologue": "speech",
    "Whispering": "speech",
    "Shout": "speech",
    "Music": "media",
    "Radio": "media",
    "Television": "media",
    "Singing": "media",
    "Soundtrack music": "media",
    "Background music": "media",
    "Sine wave": "tonal",
    "Harmonic": "tonal",
    "Whistle": "tonal",
    "Siren": "tonal",
    "Alarm": "tonal",
    "Noise": "broadband",
    "Environmental noise": "broadband",
    "White noise": "broadband",
    "Pink noise": "broadband",
    "Cacophony": "broadband",
}

SOURCES_BY_NAME: dict[str, str] = {
    "Engine": "engine",
    "Light engine (high frequency)": "engine",
    "Medium engine (mid frequency)": "engine",
    "Heavy engine (low frequency)": "engine",
    "Engine knocking": "engine",
    "Engine starting": "engine",
    "Idling": "engine",
    "Accelerating, revving, vroom": "engine",
    "Tire squeal": "tire",
    "Skidding": "tire",
    "Traffic noise, roadway noise": "road_texture",
    "Car passing by": "road_texture",
    "Wind": "aero",
    "Wind noise (microphone)": "aero",
    "Whoosh, swoosh, swish": "aero",
    "Mechanical fan": "fan",
    "Air conditioning": "fan",
    "Hair dryer": "fan",
    "Rattle": "panel_rattle",
    "Creak": "panel_rattle",
    "Squeak": "panel_rattle",
    "Vibration": "panel_rattle",
    "Clatter": "panel_rattle",
    "Mains hum": "inverter",
    "Hum": "inverter",
    "Speech": "other",
    "Music": "other",
}


def _load_names() -> list[str]:
    names = [""] * 527
    with _CSV_PATH.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            idx = int(row["index"])
            names[idx] = str(row["display_name"])
    if names[0] != "Speech" or any(not n for n in names):
        raise RuntimeError("AudioSet class_labels_indices.csv is incomplete")
    return names


AUDIOSET_NAMES: list[str] = _load_names()


def map_audioset_topk(
    probs: list[float] | tuple[float, ...],
    *,
    k: int = 5,
    min_score: float = 0.05,
) -> dict[str, Any]:
    """Pick NVH category/sources from AudioSet sigmoid probabilities."""
    if len(probs) != 527:
        raise ValueError(f"expected 527 probabilities, got {len(probs)}")
    ranked = sorted(range(527), key=lambda i: float(probs[i]), reverse=True)
    topk: list[dict[str, Any]] = []
    for i in ranked:
        score = float(probs[i])
        if score < min_score and topk:
            break
        if score < min_score:
            continue
        topk.append({"index": i, "name": AUDIOSET_NAMES[i], "score": score})
        if len(topk) >= k:
            break

    best_cat: str | None = None
    best_cat_score = -1.0
    sources: list[str] = []
    for row in topk:
        name = str(row["name"])
        cat = CATEGORY_BY_NAME.get(name)
        if cat and cat in _CATEGORY_VALUES and float(row["score"]) > best_cat_score:
            best_cat = cat
            best_cat_score = float(row["score"])
        src = SOURCES_BY_NAME.get(name)
        if src and src in _SOURCE_VALUES and src not in sources:
            sources.append(src)

    return {
        "noise_category": best_cat,
        "noise_sources": sources,
        "topk": topk,
        "mapped": best_cat is not None,
    }


def format_ast_hypothesis(
    mapped: dict[str, Any],
    *,
    heuristic_leq: float | None = None,
    heuristic_quality: str | None = None,
) -> str:
    parts = []
    for row in mapped.get("topk") or []:
        parts.append(f"{row['name']}={float(row['score']):.2f}")
    top = "; ".join(parts) if parts else "(none)"
    cat = mapped.get("noise_category") or "—"
    src = mapped.get("noise_sources") or []
    src_txt = "[" + ",".join(src) + "]" if src else "[]"
    heur = ""
    if heuristic_leq is not None or heuristic_quality:
        leq = f"leq={heuristic_leq:.1f}dB" if heuristic_leq is not None else ""
        q = f"quality={heuristic_quality}" if heuristic_quality else ""
        heur = " | heuristic: " + " ".join(x for x in (leq, q) if x)
    return f"ast:nvh_sem_ast top5: {top} → category={cat} sources={src_txt}{heur}"
