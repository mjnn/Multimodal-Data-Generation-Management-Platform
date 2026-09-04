### Task 2: 条件表达式求值

**Files:**
- Create: `hmi/backend/hmi/platform/graph_expr.py`
- Modify: `hmi/backend/hmi/platform/recipe_graph.py`（`validate_graph` 调用 `validate_condition`）
- Test: `hmi/backend/scripts/test_platform_recipe_graph.py`

**Interfaces:**
- Consumes: `condition: dict`, `ctx: dict[str, Any]`
- Produces: `FIELD_WHITELIST`; `OPS`; `validate_condition(condition, *, after_label: bool) -> dict`; `eval_condition(condition, ctx) -> bool`

- [ ] **Step 1: Write the failing tests**

Append to `test_platform_recipe_graph.py`:

```python
class TestGraphExpr(unittest.TestCase):
    def test_empty_all_is_true(self) -> None:
        from hmi.platform.graph_expr import eval_condition

        self.assertTrue(eval_condition({"all": []}, {}))

    def test_and_kind_and_confidence(self) -> None:
        from hmi.platform.graph_expr import eval_condition

        cond = {
            "all": [
                {"field": "source.kind", "op": "in", "value": ["rosbag", "video"]},
                {"field": "asr.avg_confidence", "op": "gte", "value": 0.6},
            ]
        }
        self.assertTrue(eval_condition(cond, {"source": {"kind": "rosbag"}, "asr": {"avg_confidence": 0.9}}))
        self.assertFalse(eval_condition(cond, {"source": {"kind": "audio"}, "asr": {"avg_confidence": 0.9}}))

    def test_missing_field_is_false(self) -> None:
        from hmi.platform.graph_expr import eval_condition

        cond = {"all": [{"field": "asr.has_text", "op": "eq", "value": True}]}
        self.assertFalse(eval_condition(cond, {}))

    def test_labels_dotpath(self) -> None:
        from hmi.platform.graph_expr import eval_condition

        cond = {"all": [{"field": "labels.cabin.scene", "op": "eq", "value": "highway"}]}
        self.assertTrue(eval_condition(cond, {"labels": {"cabin": {"scene": "highway"}}}))

    def test_reject_unknown_field_before_label(self) -> None:
        from hmi.platform.graph_expr import validate_condition

        with self.assertRaises(ValueError):
            validate_condition({"all": [{"field": "labels.x", "op": "eq", "value": 1}]}, after_label=False)

    def test_reject_js(self) -> None:
        from hmi.platform.graph_expr import validate_condition

        with self.assertRaises(ValueError):
            validate_condition({"all": [{"field": "source.kind", "op": "eval", "value": "1"}]}, after_label=False)
```

- [ ] **Step 2: Run to verify fail**

Run: `py -3 scripts/test_platform_recipe_graph.py TestGraphExpr -v`  
working_directory: `hmi/backend`  
Expected: FAIL import `graph_expr`

- [ ] **Step 3: Implement `graph_expr.py`**

```python
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
    }
)
POST_LABEL_FIELDS = frozenset({"label.avg_confidence"})


def _field_ok(field: str, *, after_label: bool) -> bool:
    if field in BASE_FIELDS:
        return True
    if after_label and field in POST_LABEL_FIELDS:
        return True
    if after_label and field.startswith("labels.") and len(field) > 7:
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
```

In `validate_graph`, after normalizing if nodes, compute `after_label = node["key"] in label_reach` (review/export already use this). For if nodes, `after_label = ik in _reachable(label_key, adj)` then `item["condition"] = validate_condition(item.get("condition"), after_label=after_label)`.

- [ ] **Step 4: Re-run**

Run: `py -3 scripts/test_platform_recipe_graph.py -v`  
working_directory: `hmi/backend`  
Expected: all PASS

---

