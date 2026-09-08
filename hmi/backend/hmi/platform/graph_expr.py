"""If/else condition: whitelist fields, one-level AND, no eval."""

from __future__ import annotations

from typing import Any

OPS = frozenset({"eq", "neq", "gt", "gte", "lt", "lte", "in", "not_in", "exists", "not_exists"})
BASE_FIELDS = frozenset(
    {
        "source.kind",
        "source.slot_id",
        "asr.avg_confidence",
        "asr.has_text",
        "json_extract.value",
    }
)
POST_LABEL_FIELDS = frozenset({"label.avg_confidence"})
FIELD_WHITELIST = BASE_FIELDS | POST_LABEL_FIELDS


def _field_ok(field: str, *, after_label: bool) -> bool:
    if field in BASE_FIELDS:
        return True
    if after_label and field in POST_LABEL_FIELDS:
        return True
    if after_label and field.startswith("labels.") and len(field) > 7:
        return True
    if field.startswith("json_extract.") and len(field) > 13:
        return True
    if field.endswith(".value"):
        prefix = field[: -len(".value")]
        if prefix and all(ch.isalnum() or ch in "-_." for ch in prefix):
            return True
    return False


def validate_condition(condition: Any, *, after_label: bool) -> dict[str, Any]:
    if condition is None:
        return {"all": []}
    if not isinstance(condition, dict):
        raise ValueError("condition must be an object")
    raw = condition.get("all")
    if raw is None:
        return {"all": []}
    if not isinstance(raw, list):
        raise ValueError("condition.all must be a list")
    out: list[dict[str, Any]] = []
    for pred in raw:
        if not isinstance(pred, dict):
            raise ValueError("each predicate must be an object")
        field = str(pred.get("field") or "").strip()
        op = str(pred.get("op") or "").strip()
        if not _field_ok(field, after_label=after_label):
            raise ValueError(f"condition field not allowed: {field!r}")
        if op not in OPS:
            raise ValueError(f"unknown condition op={op!r}")
        item: dict[str, Any] = {"field": field, "op": op}
        if op not in {"exists", "not_exists"}:
            item["value"] = pred.get("value")
        out.append(item)
    return {"all": out}


def _lookup(ctx: dict[str, Any], field: str) -> Any:
    if field.startswith("labels."):
        cur: Any = ctx.get("labels")
        for part in field.split(".")[1:]:
            if not isinstance(cur, dict) or part not in cur:
                return None
            cur = cur[part]
        return cur
    cur: Any = ctx
    for part in field.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _cmp(op: str, left: Any, right: Any) -> bool:
    if op == "exists":
        return left is not None
    if op == "not_exists":
        return left is None
    if left is None:
        return False
    if op == "eq":
        return left == right
    if op == "neq":
        return left != right
    if op == "in":
        return left in (right or [])
    if op == "not_in":
        return left not in (right or [])
    try:
        lf = float(left)
        rf = float(right)
    except (TypeError, ValueError):
        return False
    if op == "gt":
        return lf > rf
    if op == "gte":
        return lf >= rf
    if op == "lt":
        return lf < rf
    if op == "lte":
        return lf <= rf
    return False


def eval_condition(condition: dict[str, Any] | None, ctx: dict[str, Any]) -> bool:
    if not condition:
        return True
    preds = condition.get("all") if isinstance(condition, dict) else None
    if not preds:
        return True
    for pred in preds:
        if not _cmp(str(pred.get("op")), _lookup(ctx, str(pred.get("field"))), pred.get("value")):
            return False
    return True
