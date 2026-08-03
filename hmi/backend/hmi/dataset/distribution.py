"""Label distribution histograms for dataset balance preview and meta."""

from __future__ import annotations

from typing import Any


def label_value(row: dict[str, Any], balance_by_label: str) -> str | None:
    """Extract taxonomy label value for one manifest row."""
    y = row.get("y_json")
    if not isinstance(y, dict):
        return None
    val = y.get(balance_by_label)
    if val is None or val == "":
        return None
    return str(val)


def label_histogram(rows: list[dict[str, Any]], balance_by_label: str | None) -> dict[str, int]:
    if not balance_by_label:
        return {}
    out: dict[str, int] = {}
    for row in rows:
        val = label_value(row, balance_by_label)
        if val is None:
            key = "__missing__"
        else:
            key = val
        out[key] = out.get(key, 0) + 1
    return dict(sorted(out.items()))


def distribution_report(
    before_rows: list[dict[str, Any]],
    after_rows: list[dict[str, Any]],
    balance_by_label: str | None,
) -> dict[str, Any]:
    if not balance_by_label:
        return {"before": {}, "after": {}}
    return {
        "before": label_histogram(before_rows, balance_by_label),
        "after": label_histogram(after_rows, balance_by_label),
    }


def embedding_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    schemas: set[str] = set()
    model_versions: set[str] = set()
    for row in rows:
        x = row.get("x_json")
        if not isinstance(x, dict):
            continue
        schema = x.get("schema")
        if schema:
            schemas.add(str(schema))
        mv = x.get("model_version")
        if mv:
            model_versions.add(str(mv))
        if schema == "frame_embeddings_v1":
            for item in x.get("items") or []:
                imv = item.get("model_version") if isinstance(item, dict) else None
                if imv:
                    model_versions.add(str(imv))
    return {
        "schemas": sorted(schemas),
        "model_versions": sorted(model_versions),
    }
