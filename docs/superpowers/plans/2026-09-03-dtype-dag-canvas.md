# DataType DAG 画板 + 产物橱窗 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** DataType 编辑器改成可连线的执行 DAG；本地 worker 按图跑 if/else；工作空间详情锁死标签树；上云仍只跑投影出的线性公共前缀。

**Architecture:** `recipe.graph`（nodes + edges）是编辑器与本地执行的权威。保存时 `project_graph` 写出 `slots` / `preprocess` / `stages` / `bbox`。无 graph 的旧配方打开时 `hydrate_graph` 在内存生成一条链。本地 `graph_runtime.execute` 只沿命中的边调用已有 op 适配器；无 graph 仍走今日 overlay + `plan_and_run`。橱窗继续用 `overview.list/detail`，`hydrate_overview` 保证详情第一张卡是 `labels_tree`。

**Tech Stack:** Python 3 / FastAPI `hmi/backend/hmi/platform/`；React 19 + `@xyflow/react`；单测 `hmi/backend/scripts/test_platform_*.py`；Playwright `hmi/frontend/e2e/platform-dtype-editor.spec.ts`。Windows 前端必须 `npm.cmd` / `npx.cmd` / `cmd /c`，禁止直接 `npm`。

**Spec:** `docs/superpowers/specs/2026-09-03-dtype-dag-canvas-design.md`（已审通过）

## Global Constraints

- 不改 `pipeline/dataworks/**`、不改 DPE 镜像、不把 graph pickle 进 UDF
- 不 publish `audio_nvh-v2`；不宣称 IVI 业务打标完成
- 不抢跑 `UI-NVH-REVIEW-SAVE`
- 禁止并行 join；允许 if 两出边互斥汇合到同一节点
- 表达式禁止 `eval` / JS；只有白名单字段 + 一层 `all`
- 无 `recipe.graph` 时本地执行必须与今日等价
- 不要 git commit，除非用户在该会话明确要求
- 收工回写 CURRENT / tracking.csv（UTF-8 BOM）/ progress-board / changelog / `acceptance/UI-DTYPE-DAG-CANVAS.md`（A / A-E2E / H）
- 后端测试：`py -3 scripts/test_….py`（working_directory = `hmi/backend`）
- 前端类型：`hmi/frontend` 下 `cmd /c "npx.cmd tsc -b"`
- Playwright：`hmi/frontend` 下 `cmd /c "npx.cmd playwright test e2e/platform-dtype-editor.spec.ts"`

## File map

| 文件 | 职责 |
|------|------|
| `hmi/backend/hmi/platform/recipe_graph.py` | 图校验、线性→图 hydrate、图→线性投影、lossy 检测 |
| `hmi/backend/hmi/platform/graph_expr.py` | if 条件 AND 求值 |
| `hmi/backend/hmi/platform/graph_runtime.py` | 本地沿边执行 + 适配器注册表 |
| `hmi/backend/hmi/platform/recipe.py` | `validate_recipe` 接入 graph；ivi 种子 `label.enabled=true` |
| `hmi/backend/hmi/platform/views.py` | widget `labels_tree`；`hydrate_overview` 锁死插入 |
| `hmi/backend/hmi/platform/recipe_pipeline.py` | 有 graph 时 compile 走投影；删「必须最后」语义 |
| `hmi/backend/hmi/services/local_sdk_worker.py` | 有 graph 则 `graph_runtime`，否则旧路径 |
| `hmi/frontend/src/utils/recipeGraph.ts` | 与后端 hydrate/project 镜像 |
| `hmi/frontend/src/components/datatype/PipelineDagCanvas.tsx` | xyflow 画布 + 组件栏 |
| `hmi/frontend/src/components/datatype/DagNodeInspector.tsx` | 参数 / 条件检查器 |
| `hmi/frontend/src/components/datatype/OverviewComposer.tsx` | 禁止删/换 `labels_tree` 卡 |
| `hmi/frontend/src/pages/DataTypeEditorPage.tsx` | 保存带 `graph`；黄警告 |
| `hmi/frontend/src/pages/ClipExplorerPage.tsx` | 渲染 `labels_tree` |
| `hmi/backend/scripts/test_platform_recipe_graph.py` | 切片 A + E 投影 |
| `hmi/backend/scripts/test_platform_graph_runtime.py` | 切片 D |
| `hmi/frontend/e2e/platform-dtype-editor.spec.ts` | 画板 + 锁树 |

切片顺序：Task 1–5 = A；6–8 = B+E；9 = C；10–11 = D；12 = A-E2E + 验收。

---

### Task 1: 图校验（无环、打标器必经、if 端口）

**Files:**
- Create: `hmi/backend/hmi/platform/recipe_graph.py`
- Test: `hmi/backend/scripts/test_platform_recipe_graph.py`

**Interfaces:**
- Consumes: `graph: dict` with `nodes: list[dict]`, `edges: list[dict]`
- Produces: `validate_graph(graph: dict[str, Any]) -> dict[str, Any]`（规范化副本或 `ValueError`）；`NODE_TYPES = ("source", "op", "if", "label", "review", "export")`

- [ ] **Step 1: Write the failing test**

Create `hmi/backend/scripts/test_platform_recipe_graph.py`:

```python
"""UI-DTYPE-DAG-CANVAS: recipe.graph validate / hydrate / project."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "hmi" / "backend"))
sys.path.insert(0, str(REPO / "shared"))


def _chain() -> dict:
    return {
        "nodes": [
            {"key": "src", "type": "source", "op_id": "source", "title": "源", "params": {}, "position": {"x": 0, "y": 0}},
            {"key": "asr", "type": "op", "op_id": "audio_asr", "title": "ASR", "params": {}, "position": {"x": 0, "y": 80}},
            {"key": "lab", "type": "label", "op_id": "label", "title": "打标器", "params": {}, "position": {"x": 0, "y": 160}},
        ],
        "edges": [
            {"id": "e1", "source": "src", "source_port": "out", "target": "asr", "target_port": "in"},
            {"id": "e2", "source": "asr", "source_port": "out", "target": "lab", "target_port": "in"},
        ],
    }


class TestValidateGraph(unittest.TestCase):
    def test_valid_chain_roundtrip(self) -> None:
        from hmi.platform.recipe_graph import validate_graph

        out = validate_graph(_chain())
        self.assertEqual(len(out["nodes"]), 3)
        self.assertEqual(len(out["edges"]), 2)

    def test_rejects_cycle(self) -> None:
        from hmi.platform.recipe_graph import validate_graph

        g = _chain()
        g["edges"].append({"id": "loop", "source": "lab", "source_port": "out", "target": "asr", "target_port": "in"})
        with self.assertRaises(ValueError) as ctx:
            validate_graph(g)
        self.assertIn("cycle", str(ctx.exception).lower())

    def test_requires_exactly_one_label(self) -> None:
        from hmi.platform.recipe_graph import validate_graph

        g = _chain()
        g["nodes"] = [n for n in g["nodes"] if n["type"] != "label"]
        g["edges"] = [e for e in g["edges"] if e["target"] != "lab"]
        with self.assertRaises(ValueError):
            validate_graph(g)

    def test_required_source_must_reach_label(self) -> None:
        from hmi.platform.recipe_graph import validate_graph

        g = _chain()
        g["nodes"].append(
            {
                "key": "orphan",
                "type": "source",
                "op_id": "source",
                "title": "孤立源",
                "params": {"required": True},
                "position": {"x": 200, "y": 0},
            }
        )
        with self.assertRaises(ValueError) as ctx:
            validate_graph(g)
        self.assertIn("打标", str(ctx.exception))

    def test_if_requires_then_else_ports(self) -> None:
        from hmi.platform.recipe_graph import validate_graph

        g = _chain()
        g["nodes"].insert(
            2,
            {"key": "iff", "type": "if", "title": "if", "params": {}, "condition": {"all": []}, "position": {"x": 0, "y": 120}},
        )
        g["edges"] = [
            {"id": "e1", "source": "src", "source_port": "out", "target": "asr", "target_port": "in"},
            {"id": "e2", "source": "asr", "source_port": "out", "target": "iff", "target_port": "in"},
            {"id": "e3", "source": "iff", "source_port": "then", "target": "lab", "target_port": "in"},
        ]
        with self.assertRaises(ValueError):
            validate_graph(g)

    def test_review_before_label_rejected(self) -> None:
        from hmi.platform.recipe_graph import validate_graph

        g = _chain()
        g["nodes"].append({"key": "rev", "type": "review", "title": "校核", "params": {}, "position": {"x": 0, "y": 40}})
        g["edges"].append({"id": "bad", "source": "src", "source_port": "out", "target": "rev", "target_port": "in"})
        g["edges"].append({"id": "bad2", "source": "rev", "source_port": "out", "target": "asr", "target_port": "in"})
        with self.assertRaises(ValueError):
            validate_graph(g)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3 scripts/test_platform_recipe_graph.py -v`  
working_directory: `hmi/backend`  
Expected: FAIL `ModuleNotFoundError: hmi.platform.recipe_graph`

- [ ] **Step 3: Write minimal `validate_graph`**

Create `hmi/backend/hmi/platform/recipe_graph.py`:

```python
"""recipe.graph validate / hydrate / project (UI-DTYPE-DAG-CANVAS)."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

NODE_TYPES = ("source", "op", "if", "label", "review", "export")
IF_OUT_PORTS = ("then", "else")


def _nodes(graph: dict[str, Any]) -> list[dict[str, Any]]:
    raw = graph.get("nodes")
    if not isinstance(raw, list) or not raw:
        raise ValueError("graph.nodes must be a non-empty list")
    return raw


def _edges(graph: dict[str, Any]) -> list[dict[str, Any]]:
    raw = graph.get("edges")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("graph.edges must be a list")
    return raw


def _adj(edges: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for e in edges:
        src = str(e.get("source") or "")
        out.setdefault(src, []).append(e)
    return out


def _has_cycle(keys: set[str], adj: dict[str, list[dict[str, Any]]]) -> bool:
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {k: WHITE for k in keys}

    def dfs(u: str) -> bool:
        color[u] = GRAY
        for e in adj.get(u, []):
            v = str(e.get("target") or "")
            if v not in color:
                continue
            if color[v] == GRAY:
                return True
            if color[v] == WHITE and dfs(v):
                return True
        color[u] = BLACK
        return False

    return any(color[k] == WHITE and dfs(k) for k in keys)


def _reachable(start: str, adj: dict[str, list[dict[str, Any]]]) -> set[str]:
    seen = {start}
    stack = [start]
    while stack:
        u = stack.pop()
        for e in adj.get(u, []):
            v = str(e.get("target") or "")
            if v and v not in seen:
                seen.add(v)
                stack.append(v)
    return seen


def _reaches_label(start: str, label_key: str, adj: dict[str, list[dict[str, Any]]]) -> bool:
    return label_key in _reachable(start, adj)


def validate_graph(graph: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(graph, dict):
        raise ValueError("graph must be an object")
    out = deepcopy(graph)
    nodes = _nodes(out)
    edges = _edges(out)
    by_key: dict[str, dict[str, Any]] = {}
    labels: list[str] = []
    norm_nodes: list[dict[str, Any]] = []
    for node in nodes:
        if not isinstance(node, dict):
            raise ValueError("graph node must be an object")
        key = str(node.get("key") or "").strip()
        ntype = str(node.get("type") or "").strip()
        if not key:
            raise ValueError("graph node.key is required")
        if ntype not in NODE_TYPES:
            raise ValueError(f"unknown graph node type={ntype!r}")
        if key in by_key:
            raise ValueError(f"duplicate graph node key={key!r}")
        pos = node.get("position") if isinstance(node.get("position"), dict) else {}
        item = {
            "key": key,
            "type": ntype,
            "op_id": str(node.get("op_id") or ("source" if ntype == "source" else ntype)).strip(),
            "title": str(node.get("title") or key).strip() or key,
            "params": dict(node.get("params") or {}) if isinstance(node.get("params"), dict) else {},
            "position": {
                "x": float(pos.get("x") or 0),
                "y": float(pos.get("y") or 0),
            },
        }
        if ntype == "if":
            item["condition"] = node.get("condition") if isinstance(node.get("condition"), dict) else {"all": []}
        if ntype == "label":
            item["op_id"] = "label"
            labels.append(key)
        if ntype == "source":
            item["params"].setdefault("required", True)
        by_key[key] = item
        norm_nodes.append(item)
    if len(labels) != 1:
        raise ValueError("graph must contain exactly one label node")
    label_key = labels[0]
    norm_edges: list[dict[str, Any]] = []
    for i, edge in enumerate(edges):
        if not isinstance(edge, dict):
            raise ValueError("graph edge must be an object")
        src = str(edge.get("source") or "").strip()
        tgt = str(edge.get("target") or "").strip()
        sp = str(edge.get("source_port") or "out").strip() or "out"
        tp = str(edge.get("target_port") or "in").strip() or "in"
        if src not in by_key or tgt not in by_key:
            raise ValueError(f"graph edge references unknown node {src!r}->{tgt!r}")
        if by_key[src]["type"] == "if" and sp not in IF_OUT_PORTS:
            raise ValueError("if node outgoing port must be then or else")
        eid = str(edge.get("id") or f"e{i}").strip() or f"e{i}"
        norm_edges.append({"id": eid, "source": src, "source_port": sp, "target": tgt, "target_port": tp})
    adj = _adj(norm_edges)
    if _has_cycle(set(by_key), adj):
        raise ValueError("graph contains a cycle")
    if_keys = [k for k, n in by_key.items() if n["type"] == "if"]
    for ik in if_keys:
        ports = {str(e.get("source_port")) for e in adj.get(ik, [])}
        if "then" not in ports:
            raise ValueError("if node must have a then outgoing edge")
        if "else" not in ports:
            raise ValueError("if node must have an else outgoing edge")
    for node in norm_nodes:
        if node["type"] != "source":
            continue
        required = bool(node["params"].get("required", True))
        if required and not _reaches_label(node["key"], label_key, adj):
            raise ValueError("必选数据源必须能到达打标器")
    label_reach = _reachable(label_key, adj)
    for node in norm_nodes:
        if node["type"] in {"review", "export"} and node["key"] not in label_reach:
            raise ValueError("review/export 必须在打标器之后")
    out["nodes"] = norm_nodes
    out["edges"] = norm_edges
    return out
```

If `audio_asr` is not a real op_id in the catalog, keep it only in this isolated graph fixture — `validate_graph` does not look up operators in Task 1.

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3 scripts/test_platform_recipe_graph.py -v`  
working_directory: `hmi/backend`  
Expected: `test_if_requires_then_else_ports` FAIL until else edge exists — the fixture only has `then`. That is intended. All six tests PASS after Step 3 (`test_if_requires_then_else_ports` raises because else missing).

- [ ] **Step 5: Commit only if the user asked**

Skip unless explicitly requested.

---

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

### Task 3: 线性配方 hydrate 成链图

**Files:**
- Modify: `hmi/backend/hmi/platform/recipe_graph.py`
- Test: `hmi/backend/scripts/test_platform_recipe_graph.py`

**Interfaces:**
- Consumes: `hydrate_recipe_to_steps` from `recipe_pipeline.py`
- Produces: `hydrate_graph(recipe: dict[str, Any]) -> dict[str, Any]` — if `recipe.graph` present, `validate_graph` it; else build a chain from existing cards and return graph **without writing the recipe**

- [ ] **Step 1: Failing test**

```python
class TestHydrateGraph(unittest.TestCase):
    def test_oms_cabin_chain_has_label(self) -> None:
        from hmi.platform.recipe import SEED_RECIPES, validate_recipe
        from hmi.platform.recipe_graph import hydrate_graph, validate_graph

        rec = validate_recipe(SEED_RECIPES["oms_cabin"])
        self.assertFalse(rec.get("graph"))
        g = hydrate_graph(rec)
        validate_graph(g)
        types = [n["type"] for n in g["nodes"]]
        self.assertIn("source", types)
        self.assertEqual(types.count("label"), 1)
        keys = [n["key"] for n in g["nodes"]]
        # chain: each edge target index > source index in node list
        idx = {k: i for i, k in enumerate(keys)}
        for e in g["edges"]:
            self.assertLess(idx[e["source"]], idx[e["target"]])

    def test_existing_graph_not_rebuilt(self) -> None:
        from hmi.platform.recipe import SEED_RECIPES, validate_recipe
        from hmi.platform.recipe_graph import hydrate_graph

        rec = dict(validate_recipe(SEED_RECIPES["oms_cabin"]))
        rec["graph"] = hydrate_graph(rec)
        rec["graph"]["nodes"][0]["title"] = "自定义源名"
        again = hydrate_graph(rec)
        self.assertEqual(again["nodes"][0]["title"], "自定义源名")
```

- [ ] **Step 2: Run — expect FAIL** `hydrate_graph` missing

- [ ] **Step 3: Implement**

```python
def hydrate_graph(recipe: dict[str, Any]) -> dict[str, Any]:
    raw = recipe.get("graph")
    if isinstance(raw, dict) and raw.get("nodes"):
        return validate_graph(raw)
    from hmi.platform.recipe_pipeline import hydrate_recipe_to_steps

    steps = hydrate_recipe_to_steps(recipe)
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    prev: str | None = None
    y = 0
    for step in steps:
        key = str(step.get("key") or "").strip()
        if not key:
            continue
        op_id = str(step.get("op_id") or "")
        if step.get("card_kind") == "source" or op_id == "source":
            ntype = "source"
        elif op_id == "label":
            ntype = "label"
        else:
            ntype = "op"
        nodes.append(
            {
                "key": key,
                "type": ntype,
                "op_id": op_id or ntype,
                "title": str(step.get("title") or key),
                "params": dict(step.get("params") or {}),
                "position": {"x": 80, "y": y},
            }
        )
        if prev:
            edges.append(
                {
                    "id": f"{prev}->{key}",
                    "source": prev,
                    "source_port": "out",
                    "target": key,
                    "target_port": "in",
                }
            )
        prev = key
        y += 96
    if not any(n["type"] == "label" for n in nodes):
        nodes.append(
            {
                "key": "stage-label",
                "type": "label",
                "op_id": "label",
                "title": "打标器",
                "params": {},
                "position": {"x": 80, "y": y},
            }
        )
        if prev:
            edges.append(
                {
                    "id": f"{prev}->stage-label",
                    "source": prev,
                    "source_port": "out",
                    "target": "stage-label",
                    "target_port": "in",
                }
            )
    return validate_graph({"nodes": nodes, "edges": edges})
```

If `hydrate_recipe_to_steps` already inserts a label card for oms_cabin, the extra insert is skipped. For `ivi_ui_stub` before seed change, this function **adds** `stage-label` so `validate_graph` passes.

- [ ] **Step 4: Run** `py -3 scripts/test_platform_recipe_graph.py TestHydrateGraph -v` Expected: PASS

---

### Task 4: 图投影公共前缀

**Files:**
- Modify: `hmi/backend/hmi/platform/recipe_graph.py`
- Test: `hmi/backend/scripts/test_platform_recipe_graph.py`

**Interfaces:**
- Produces: `project_graph(graph: dict[str, Any]) -> dict[str, Any]` with keys `slots`, `preprocess`, `products`, `stages`, `bbox`, `require_any_kinds`
- Produces: `graph_is_lossy(graph: dict[str, Any]) -> bool` — True if any `if` / `review` / `export` node exists

**公共前缀算法（钉死）：** 从每个必选 source BFS。遇到 `type==if` **停止向下计入 preprocess**（if 本身不是 op）。`then`/`else` 子图里的 `op` 都不进 `preprocess`。if 之前、且能到达 label 的 `op` 按一种稳定序（节点在 `nodes` 数组中的顺序）写入 `preprocess`。`embed`：若其节点在该前缀集合中则 `stages.embed.enabled=True`。`detect_bbox` 同理 → `bbox.enabled`。`label` 永远 `stages.label.enabled=True`。

- [ ] **Step 1: Failing tests**

```python
class TestProjectGraph(unittest.TestCase):
    def test_chain_projects_asr_into_preprocess(self) -> None:
        from hmi.platform.recipe_graph import project_graph, validate_graph

        g = validate_graph(_chain())
        proj = project_graph(g)
        self.assertEqual(proj["slots"][0]["id"], "src")
        self.assertTrue(proj["stages"]["label"]["enabled"])
        ops = [p["op_id"] for p in proj["preprocess"]]
        self.assertEqual(ops, ["audio_asr"])

    def test_then_only_op_not_in_preprocess(self) -> None:
        from hmi.platform.recipe_graph import graph_is_lossy, project_graph, validate_graph

        g = {
            "nodes": [
                {"key": "src", "type": "source", "op_id": "source", "title": "源", "params": {}, "position": {"x": 0, "y": 0}},
                {"key": "iff", "type": "if", "title": "if", "condition": {"all": []}, "params": {}, "position": {"x": 0, "y": 80}},
                {"key": "fr", "type": "op", "op_id": "extract_frames", "title": "抽帧", "params": {}, "position": {"x": 0, "y": 160}},
                {"key": "lab", "type": "label", "op_id": "label", "title": "打标", "params": {}, "position": {"x": 0, "y": 240}},
            ],
            "edges": [
                {"id": "a", "source": "src", "source_port": "out", "target": "iff", "target_port": "in"},
                {"id": "b", "source": "iff", "source_port": "then", "target": "fr", "target_port": "in"},
                {"id": "c", "source": "iff", "source_port": "else", "target": "lab", "target_port": "in"},
                {"id": "d", "source": "fr", "source_port": "out", "target": "lab", "target_port": "in"},
            ],
        }
        g = validate_graph(g)
        proj = project_graph(g)
        self.assertEqual(proj["preprocess"], [])
        self.assertTrue(graph_is_lossy(g))
        self.assertTrue(proj["stages"]["label"]["enabled"])
```

If `audio_asr` is rejected later by `validate_recipe` (unknown op), Task 4 `project_graph` still emits it; `validate_recipe` in Task 5 only accepts catalog ops — keep `_chain` using a real preprocess op from `OPERATORS`. Check `hmi/backend/hmi/platform/operators.py` and replace `audio_asr` with an existing id (e.g. `mel_spectrogram` or whatever ASR is actually called, often `asr` or `audio_asr`). **Do this lookup in Task 4 Step 3** and fix `_chain()` to use a real `op_id` from `OPERATORS` so Task 5 roundtrip works. If no ASR op exists, use `extract_frames`.

- [ ] **Step 2: Run — expect FAIL** `project_graph` missing

- [ ] **Step 3: Implement `project_graph` / `graph_is_lossy`**

Use `slots_from_steps`-compatible slot dicts: `id=source.key`, `title`, `kinds` from `params.kinds` or `["video"]` default only if missing — prefer copying `params` kinds list. For hydrate-from-seed, source nodes should copy kinds from the card in Task 3:

Update Task 3 `hydrate_graph` source nodes to include `"params": {**step.params, "kinds": step.get("kinds"), "required": step.get("required", True), "cardinality_min": ..., "cardinality_max": ...}`.

`project_graph` slots:

```python
def graph_is_lossy(graph: dict[str, Any]) -> bool:
    g = validate_graph(graph)
    return any(n["type"] in {"if", "review", "export"} for n in g["nodes"])


def _prefix_op_keys(g: dict[str, Any]) -> list[str]:
    nodes = {n["key"]: n for n in g["nodes"]}
    adj = _adj(g["edges"])
    blocked: set[str] = set()

    def mark_from(start: str) -> None:
        stack = [start]
        seen = {start}
        while stack:
            u = stack.pop()
            blocked.add(u)
            for e in adj.get(u, []):
                v = str(e.get("target") or "")
                if v and v not in seen:
                    seen.add(v)
                    stack.append(v)

    for n in g["nodes"]:
        if n["type"] != "if":
            continue
        for e in adj.get(n["key"], []):
            tgt = str(e.get("target") or "")
            if tgt:
                mark_from(tgt)
    prefix: list[str] = []
    for n in g["nodes"]:
        if n["type"] == "op" and n["key"] not in blocked:
            prefix.append(n["key"])
    return prefix


def project_graph(graph: dict[str, Any]) -> dict[str, Any]:
    from hmi.platform.recipe_pipeline import _require_any_kinds_from_slots

    g = validate_graph(graph)
    nodes = {n["key"]: n for n in g["nodes"]}
    slots = []
    for n in g["nodes"]:
        if n["type"] != "source":
            continue
        p = n["params"]
        kinds = list(p.get("kinds") or ["video"])
        slots.append(
            {
                "id": n["key"],
                "title": n["title"],
                "kinds": kinds,
                "cardinality_min": int(p.get("cardinality_min") or 1),
                "cardinality_max": int(p.get("cardinality_max") or 1),
                "role": str(p.get("role") or "input"),
                "required": bool(p.get("required", True)),
            }
        )
    prefix_keys = _prefix_op_keys(g)
    preprocess = []
    products = []
    bbox = {"enabled": False, "detector": "opencv", "yolo_classes": ""}
    embed_enabled = False
    for key in prefix_keys:
        n = nodes[key]
        op_id = str(n.get("op_id") or "")
        if op_id == "embed":
            embed_enabled = True
            continue
        if op_id == "detect_bbox":
            bbox = {
                "enabled": True,
                "detector": str(n["params"].get("detector") or "opencv"),
                "yolo_classes": str(n["params"].get("yolo_classes") or ""),
            }
        entry: dict[str, Any] = {"op_id": op_id, "when_kind": n["params"].get("when_kind"), "required": False}
        produces = n["params"].get("produces")
        if produces:
            entry["produces"] = list(produces)
            for name in produces:
                products.append({"id": name, "from_op": op_id, "reusable": True})
        preprocess.append(entry)
    return {
        "slots": slots,
        "preprocess": preprocess,
        "products": products,
        "stages": {"label": {"enabled": True}, "embed": {"enabled": embed_enabled}},
        "bbox": bbox,
        "require_any_kinds": _require_any_kinds_from_slots(slots),
    }
```

If `_require_any_kinds_from_slots` is private, export it or duplicate the small helper in `recipe_graph.py` (copy the existing function body from `recipe_pipeline.py` rather than importing a private name if tests complain).

- [ ] **Step 4: Run** `py -3 scripts/test_platform_recipe_graph.py TestProjectGraph -v` Expected: PASS

---

### Task 5: `validate_recipe` 接入 graph + ivi 种子 + `labels_tree` widget

**Files:**
- Modify: `hmi/backend/hmi/platform/recipe.py`（`validate_recipe` 末尾；`SEED_RECIPES["ivi_ui_stub"]`）
- Modify: `hmi/backend/hmi/platform/views.py`（widget + `hydrate_overview`）
- Modify: `hmi/backend/hmi/platform/recipe_pipeline.py`（`pin_label_last` 改为 no-op 文档：函数保留但不再强制最后，避免旧调用崩；或改为只保证 label 存在）
- Test: `hmi/backend/scripts/test_platform_recipe_graph.py` + existing `test_pin_label_last` 更新

**Interfaces:**
- `validate_recipe`: 若有 `graph`，`validate_graph` 后 `project_graph` **覆盖** slots/preprocess/stages/bbox/require_any_kinds；再 `hydrate_overview`（此时已含 labels_tree）
- ivi seed: `"stages": {"label": {"enabled": True, "model": "default"}, "embed": {"enabled": False}}`

- [ ] **Step 1: Failing tests**

```python
class TestRecipeGraphIntegration(unittest.TestCase):
    def test_validate_recipe_projects_graph(self) -> None:
        from hmi.platform.recipe import SEED_RECIPES, validate_recipe
        from hmi.platform.recipe_graph import hydrate_graph

        rec = dict(validate_recipe(SEED_RECIPES["oms_cabin"]))
        rec["graph"] = hydrate_graph(rec)
        out = validate_recipe(rec)
        self.assertTrue(out["graph"]["nodes"])
        self.assertTrue(out["stages"]["label"]["enabled"])
        self.assertEqual(out["overview"]["detail"][0]["widget_id"], "labels_tree")

    def test_ivi_seed_label_enabled(self) -> None:
        from hmi.platform.recipe import SEED_RECIPES, validate_recipe

        out = validate_recipe(SEED_RECIPES["ivi_ui_stub"])
        self.assertTrue(out["stages"]["label"]["enabled"])
```

Also change `test_pin_label_last` in `test_platform_datatype_editor.py` to:

```python
    def test_pin_label_last_keeps_label_present_not_forced_last(self) -> None:
        from hmi.platform.recipe_pipeline import pin_label_last

        steps = [
            {"op_id": "source", "card_kind": "source"},
            {"op_id": "label"},
            {"op_id": "parse_bag"},
        ]
        out = pin_label_last(steps)
        self.assertTrue(any(s.get("op_id") == "label" for s in out))
        # label may sit before parse_bag (DAG successor)
```

- [ ] **Step 2: Run — expect FAIL** ivi still `enabled: False`; no `labels_tree` widget

- [ ] **Step 3: Implement**

In `views.py` add widget before `VIEW_WIDGET_IDS`:

```python
    "labels_tree": {
        "id": "labels_tree",
        "surface": "detail",
        "title": "标签树",
        "description": "必选产物：当前 run 的 labels_json",
        "needs": ["labels_tree"],
    },
```

In `hydrate_overview`, after building `detail_cards`:

```python
    if not any(str(c.get("widget_id")) == "labels_tree" for c in detail_cards):
        detail_cards.insert(
            0,
            {
                "key": "locked-labels_tree",
                "widget_id": "labels_tree",
                "bindings": {"in": {"kind": "upstream", "step_key": "stage-label", "port_id": "labels_tree"}},
            },
        )
```

`_normalize_card_list` must allow `labels_tree` once it is in `VIEW_WIDGETS`.

In `validate_recipe` after existing overview hydrate:

```python
    graph_in = out.get("graph")
    if isinstance(graph_in, dict) and graph_in.get("nodes"):
        from hmi.platform.recipe_graph import project_graph, validate_graph

        g = validate_graph(graph_in)
        proj = project_graph(g)
        out["graph"] = g
        out["slots"] = proj["slots"]
        out["preprocess"] = proj["preprocess"]
        out["products"] = proj["products"]
        out["stages"] = proj["stages"]
        # keep label.model from original stages if projected enabled
        prev_model = ((recipe.get("stages") or {}).get("label") or {}).get("model")
        if prev_model and out["stages"]["label"].get("enabled"):
            out["stages"]["label"]["model"] = prev_model
        out["bbox"] = proj["bbox"]
        out["require_any_kinds"] = proj["require_any_kinds"]
    out["overview"] = hydrate_overview(out)
```

Call this **after** slots/preprocess were already normalized, so recipes without graph unchanged.

`pin_label_last`: return steps unchanged if a label exists; if missing, append a label card (same as today append behavior) but **do not move it to the end**.

ivi seed `label.enabled=True`.

- [ ] **Step 4: Run**

```
py -3 scripts/test_platform_recipe_graph.py -v
py -3 scripts/test_platform_datatype_editor.py -v
```

working_directory: `hmi/backend`  
Expected: both suites PASS（editor 里 `test_pin_label_last` 已改名/改断言）

---

### Task 6: 前端 graph 类型 + `recipeGraph.ts`

**Files:**
- Modify: `hmi/frontend/src/api/types.ts`
- Create: `hmi/frontend/src/utils/recipeGraph.ts`
- Modify: `hmi/frontend/src/pages/DataTypeEditorPage.tsx`（load/save `graph`）

**Interfaces:**
- `RecipeGraphNode`, `RecipeGraphEdge`, `RecipeGraph` on `DataTypeRecipe.graph?`
- `hydrateGraph(recipe)`, `graphIsLossy(graph)`, mirror backend enough for the editor (positions + types). **Do not reimplement validate in the browser as the source of truth**; still POST and show backend `ValueError`. Client-side: refuse delete label locally.

- [ ] **Step 1: Add types**

```ts
export type GraphNodeType = 'source' | 'op' | 'if' | 'label' | 'review' | 'export'

export type GraphConditionPred = { field: string; op: string; value?: unknown }
export type GraphCondition = { all: GraphConditionPred[] }

export type RecipeGraphNode = {
  key: string
  type: GraphNodeType
  op_id?: string
  title: string
  params?: Record<string, unknown>
  position: { x: number; y: number }
  condition?: GraphCondition
}

export type RecipeGraphEdge = {
  id: string
  source: string
  source_port: string
  target: string
  target_port: string
}

export type RecipeGraph = { nodes: RecipeGraphNode[]; edges: RecipeGraphEdge[] }
```

Attach `graph?: RecipeGraph` to `DataTypeRecipe`.

`recipeGraph.ts`: implement `hydrateGraphFromSteps(steps: PipelineStep[]): RecipeGraph` (same chain rules as backend Task 3) and `graphIsLossy`.

- [ ] **Step 2: `cmd /c "npx.cmd tsc -b"`** in `hmi/frontend`  
Expected: FAIL until DataTypeRecipe usages compile (optional graph is fine). After adding types, PASS.

- [ ] **Step 3: Wire editor save**

In `DataTypeEditorPage`, keep `steps` until Task 7. After Task 7, `graph` is the state. For this task only: on save, if `recipe.graph` exists send it through; if not, `hydrateGraphFromSteps(steps)` and include in PUT body. Backend Task 5 already projects.

- [ ] **Step 4: tsc PASS**

---

### Task 7: xyflow 画板替换纵向编排列表

**Files:**
- Modify: `hmi/frontend/package.json` via `cmd /c "npm.cmd install @xyflow/react"` in `hmi/frontend`（禁止裸 `npm`）
- Create: `hmi/frontend/src/components/datatype/PipelineDagCanvas.tsx`
- Modify: `hmi/frontend/src/pages/DataTypeEditorPage.tsx`（用画布替换 `PipelineOrchestrator` 的算子列表；源仍可从 palette 加 source 节点）
- Modify: `hmi/frontend/e2e/platform-dtype-editor.spec.ts`（testid 改为 DAG）

**Interfaces:**
- Canvas `data-testid="dag-canvas"`
- Palette: keep `palette-op-{op_id}`；add `palette-op-if`, `palette-op-review`, `palette-op-export`
- Nodes: `data-testid="dag-node-{key}"`；label node `dag-node-label` (also `dag-node-{labelKey}`)
- Label has no delete control (`dag-remove-label` count 0)
- Adding an op inserts a node **not** pinned last; user connects edges
- Default new recipe: one source node + one label node + one edge（`defaultNewGraph()`）

- [ ] **Step 1: Install**

working_directory: `hmi/frontend`  
`cmd /c "npm.cmd install @xyflow/react"`

- [ ] **Step 2: Minimal canvas**

`PipelineDagCanvas` wraps `ReactFlowProvider` + `ReactFlow`. Map `RecipeGraph.nodes` to xyflow nodes (`id=key`, `position`, `data={{ type, title, op_id }}`). Edges: xyflow `sourceHandle=source_port`, `targetHandle=target_port`. if node renders two handles `then` / `else` at the bottom.

On connect: append edge with `source_port` from handle id (`out`/`then`/`else`).

Palette click: append node with new key `op-{opId}-{Date.now()}`, position `{x: 320, y: 80 * nodes.length}`. Label cannot be added twice (palette label hidden if one exists). Label cannot be removed in `onNodesChange`.

Replace `PipelineOrchestrator` on the editor page with `PipelineDagCanvas`. Keep `OverviewComposer` below.

Delete or stop calling `pinLabelLast` from the editor path.

- [ ] **Step 3: Update Playwright**

Rewrite the first spec:

- `getByTestId('dag-canvas')` visible
- `palette-op-if` visible
- `dag-node-label` visible
- `dag-remove-label` count 0
- clicking `palette-op-mel_spectrogram` creates a node `dag-node-` matching `/mel_spectrogram/`
- save still works
- reopen: graph nodes still there (`dag-node-label` visible)

Remove assertions that mel Y < label Y in a **list**. Optionally: after add, both nodes exist.

STFT bind test: inspector opens on select; if too heavy for this task, keep a skip and cover bind in Task 8. Prefer: selecting the STFT node shows inspector `dag-inspector` with bind control `pipe-bind-stft_spectrogram-in` reused.

oms_cabin edit: `dag-canvas` + `dag-node-label`.

- [ ] **Step 4: tsc + playwright**

```
cmd /c "npx.cmd tsc -b"
cmd /c "npx.cmd playwright test e2e/platform-dtype-editor.spec.ts"
```

working_directory: `hmi/frontend`  
Expected: tsc PASS; playwright 3/3 (or updated count) PASS

---

### Task 8: 检查器条件 UI + 上云黄警告（切片 E）

**Files:**
- Create: `hmi/frontend/src/components/datatype/DagNodeInspector.tsx`
- Modify: `hmi/frontend/src/pages/DataTypeEditorPage.tsx`

**Interfaces:**
- If node selected (`type==if`): Form.List of predicates; field Select from `source.kind | source.slot_id | asr.avg_confidence | asr.has_text | label.avg_confidence | labels.` custom input；op Select from the 10 ops
- Warning Alert `data-testid="dag-cloud-lossy"` text exactly: `本地按图执行；上云只跑公共前缀。` when `graphIsLossy(graph)`；always show the first sentence in a muted hint `data-testid="dag-cloud-hint"`

- [ ] **Step 1: Implement inspector + alerts** (no extra unit test runner; Playwright in Task 12 covers hint)

```tsx
<Alert type="info" data-testid="dag-cloud-hint" message="本地按图执行；上云只跑公共前缀。" />
{lossy ? (
  <Alert type="warning" data-testid="dag-cloud-lossy" message="图含 if 或打标后节点：上云不会执行这些分支。" />
) : null}
```

Do not block draft or published save.

- [ ] **Step 2: tsc PASS**

---

### Task 9: 橱窗锁死 `labels_tree`（切片 C）

**Files:**
- Modify: `hmi/frontend/src/utils/overviewLayout.ts`（`ensureLabelsTree(detail)`）
- Modify: `hmi/frontend/src/components/datatype/OverviewComposer.tsx`（`widget_id==='labels_tree'` hide delete and widget switch; `data-testid="overview-locked-labels_tree"`）
- Modify: `hmi/frontend/src/pages/ClipExplorerPage.tsx` + `ReviewClipMediaPanel.tsx`（`labels_tree` 渲染 `labels_json` 树，testid `overview-runtime-labels_tree`）
- Mirror already in backend `hydrate_overview`

- [ ] **Step 1: Composer lock**

```tsx
const locked = card.widget_id === 'labels_tree'
// Delete button: {!locked && <Button ... data-testid={`overview-remove-${card.widget_id}`} />}
```

`ensureLabelsTree` on every `onChange` of detail and on preset fill.

- [ ] **Step 2: Runtime**

When `detailIds.includes('labels_tree')`, show the same `<pre>` currently used for `json_tree` but bind clip labels (`data-testid="overview-runtime-labels_tree"`). Keep `json_tree` path for structured JSON.

- [ ] **Step 3: Playwright**

On create page: `overview-locked-labels_tree` visible; `overview-remove-labels_tree` count 0.

- [ ] **Step 4: tsc + editor e2e PASS**

---

### Task 10: `graph_runtime` 调度 + 假适配器（切片 D）

**Files:**
- Create: `hmi/backend/hmi/platform/graph_runtime.py`
- Test: `hmi/backend/scripts/test_platform_graph_runtime.py`

**Interfaces:**
- `Adapter = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]`  `(node, ctx) -> ctx patch`
- `execute_graph(graph, *, ctx0: dict, adapters: dict[str, Adapter]) -> dict` returns `{ctx, run: [{key, status}]}` where status is `success|skipped`
- Walk: start from all `source` nodes (mark success, merge `source.kind` / `source.slot_id` from ctx0 or node params). Ready set = nodes whose **at least one incoming edge** was taken, or no incoming. If node has incoming, require the taken predecessor. Never wait for untaken if-branch.
- `if`: `eval_condition`; take `then` if True else `else`. Missing `else` target = no-op.
- Unknown `op_id` with no adapter → raise `RuntimeError(f"missing adapter for op_id={op_id}")`
- `label` adapter required in the map; if label never executed → `RuntimeError("打标器未执行")`
- `review` adapter may set `ctx["review_status"]="pending_review"`
- `export` adapter may set `ctx["exported_product_ids"]=list`

- [ ] **Step 1: Failing tests**

```python
class TestGraphRuntime(unittest.TestCase):
    def test_if_false_skips_then_op(self) -> None:
        from hmi.platform.graph_runtime import execute_graph
        from hmi.platform.recipe_graph import validate_graph

        g = validate_graph({
            "nodes": [
                {"key": "src", "type": "source", "op_id": "source", "title": "s", "params": {"required": True, "kinds": ["audio"]}, "position": {"x": 0, "y": 0}},
                {
                    "key": "iff",
                    "type": "if",
                    "title": "if",
                    "params": {},
                    "condition": {"all": [{"field": "asr.avg_confidence", "op": "gte", "value": 0.9}]},
                    "position": {"x": 0, "y": 80},
                },
                {"key": "fr", "type": "op", "op_id": "extract_frames", "title": "抽帧", "params": {}, "position": {"x": 0, "y": 160}},
                {"key": "lab", "type": "label", "op_id": "label", "title": "打标", "params": {}, "position": {"x": 0, "y": 240}},
            ],
            "edges": [
                {"id": "a", "source": "src", "source_port": "out", "target": "iff", "target_port": "in"},
                {"id": "b", "source": "iff", "source_port": "then", "target": "fr", "target_port": "in"},
                {"id": "c", "source": "iff", "source_port": "else", "target": "lab", "target_port": "in"},
                {"id": "d", "source": "fr", "source_port": "out", "target": "lab", "target_port": "in"},
            ],
        })
        ran = []

        def frames(_n, ctx):
            ran.append("frames")
            return ctx

        def label(_n, ctx):
            ran.append("label")
            ctx = dict(ctx)
            ctx["labels"] = {"ok": True}
            return ctx

        out = execute_graph(
            g,
            ctx0={"source": {"kind": "audio", "slot_id": "src"}, "asr": {"avg_confidence": 0.1}},
            adapters={"extract_frames": frames, "label": label},
        )
        self.assertEqual(ran, ["label"])
        statuses = {r["key"]: r["status"] for r in out["run"]}
        self.assertEqual(statuses["fr"], "skipped")
        self.assertEqual(statuses["lab"], "success")

    def test_review_sets_pending(self) -> None:
        from hmi.platform.graph_runtime import execute_graph
        from hmi.platform.recipe_graph import validate_graph

        g = validate_graph({
            "nodes": [
                {"key": "src", "type": "source", "op_id": "source", "title": "s", "params": {"required": True}, "position": {"x": 0, "y": 0}},
                {"key": "lab", "type": "label", "op_id": "label", "title": "打标", "params": {}, "position": {"x": 0, "y": 80}},
                {"key": "rev", "type": "review", "title": "校核", "params": {}, "position": {"x": 0, "y": 160}},
            ],
            "edges": [
                {"id": "a", "source": "src", "source_port": "out", "target": "lab", "target_port": "in"},
                {"id": "b", "source": "lab", "source_port": "out", "target": "rev", "target_port": "in"},
            ],
        })
        out = execute_graph(
            g,
            ctx0={"source": {"kind": "video", "slot_id": "src"}},
            adapters={"label": lambda n, c: {**c, "labels": {}}},
        )
        self.assertEqual(out["ctx"].get("review_status"), "pending_review")
```

- [ ] **Step 2: Run — expect FAIL** missing module

- [ ] **Step 3: Implement `execute_graph`**

Use a worklist. Record `taken_edges: set[str]`. When executing `if`, add only the chosen outgoing edge id to `taken_edges`. A node is runnable when every **incoming edge from a taken predecessor path** is satisfied: if all incoming edges' sources are skipped, and none taken, skip the node. XOR join: if **any** incoming edge is taken, run once.

Default adapters inside `execute_graph` for `review` / `export` / `source` / `if` so tests need not pass them. `op` and `label` must be in `adapters`.

- [ ] **Step 4: Run** `py -3 scripts/test_platform_graph_runtime.py -v` Expected: PASS  
Also re-run `test_platform_recipe_graph.py` PASS

---

### Task 11: 接入 `local_sdk_worker`（有 graph 才走解释器）

**Files:**
- Modify: `hmi/backend/hmi/services/local_sdk_worker.py`（`_run_sdk_and_ingest` 在读到 `recipe.graph.nodes` 后分支）
- Modify: `hmi/backend/hmi/platform/graph_runtime.py`（`assert_runnable_locally`、`preview_taken_op_ids`、`apply_graph_to_run_request`）

**Interfaces:**
- 无 `graph`：调用方完全走今日路径（`plan_and_run` / `_run_audio_array_spec`），零行为差
- 有 `graph`：先 `assert_runnable_locally`；再用假适配器 `preview_taken_op_ids` 得到本次会跑的 `op_id` 集合；把 `need_label` / `need_embed` / `bbox_enabled` 按 **taken** 集合写入，然后仍调用现有 `plan_and_run`（或阵列专用路径）
- `review` 在 taken 中：run 成功后对该 clip 调用 `hmi.review_db` 里现有的写入函数，`review_status="pending_review"`（打开 `review_db.py` 用真实函数名，不要编造）
- **ASR/标签之后的 if（钉死护栏）：** 若任一 if 的 `condition.all[].field` 以 `asr.` / `labels.` / `label.` 开头，`assert_runnable_locally` 抛 `RuntimeError("本地尚未拆分 plan_and_run：不能在 ASR/打标之后分支")`。图仍可保存（D10）；本地跑到该配方会失败而不是静默忽略。真正拆分 `plan_and_run` 不在本计划扩 scope，除非本任务实现中已有现成的独立 ASR API 可接（有则接；没有则只留护栏并写入 acceptance）

```python
def assert_runnable_locally(graph: dict[str, Any]) -> None:
    g = validate_graph(graph)
    for n in g["nodes"]:
        if n["type"] != "if":
            continue
        for pred in (n.get("condition") or {}).get("all") or []:
            field = str(pred.get("field") or "")
            if field.startswith("asr.") or field.startswith("labels.") or field.startswith("label."):
                raise RuntimeError("本地尚未拆分 plan_and_run：不能在 ASR/打标之后分支")
```

`preview_taken_op_ids(graph, ctx0)` = `execute_graph` + 对每个 `op`/`label` 注册 no-op adapter，返回 `status==success` 的 `op_id` 列表。

`apply_graph_to_run_request` 返回与今日 `overlay_run_request` 相同键：`need_label`、`need_embed`、`bbox_enabled` 等，来源改为 taken 集合。

- [ ] **Step 1: Failing test for the guard**

```python
    def test_assert_blocks_asr_if(self) -> None:
        from hmi.platform.graph_runtime import assert_runnable_locally
        from hmi.platform.recipe_graph import validate_graph

        g = validate_graph({
            "nodes": [
                {"key": "src", "type": "source", "op_id": "source", "title": "s", "params": {"required": True}, "position": {"x": 0, "y": 0}},
                {
                    "key": "iff",
                    "type": "if",
                    "title": "if",
                    "params": {},
                    "condition": {"all": [{"field": "asr.avg_confidence", "op": "gte", "value": 0.9}]},
                    "position": {"x": 0, "y": 80},
                },
                {"key": "lab", "type": "label", "op_id": "label", "title": "打标", "params": {}, "position": {"x": 0, "y": 160}},
            ],
            "edges": [
                {"id": "a", "source": "src", "source_port": "out", "target": "iff", "target_port": "in"},
                {"id": "b", "source": "iff", "source_port": "then", "target": "lab", "target_port": "in"},
                {"id": "c", "source": "iff", "source_port": "else", "target": "lab", "target_port": "in"},
            ],
        })
        with self.assertRaises(RuntimeError):
            assert_runnable_locally(g)
```

- [ ] **Step 2: Run** `py -3 scripts/test_platform_graph_runtime.py TestGraphRuntime.test_assert_blocks_asr_if -v`  
working_directory: `hmi/backend`  
Expected: FAIL until `assert_runnable_locally` exists

- [ ] **Step 3: Implement guard + worker branch**

After `recipe = get_data_type(...)` in `_run_sdk_and_ingest`:

```python
    graph = (recipe or {}).get("graph") if recipe else None
    if isinstance(graph, dict) and graph.get("nodes"):
        from hmi.platform.graph_runtime import apply_graph_to_run_request, assert_runnable_locally

        assert_runnable_locally(graph)
        recipe_req = apply_graph_to_run_request(graph, recipe, settings)
```

If `graph` is missing, do not call these imports; keep the current `overlay_run_request` block.

- [ ] **Step 4: Run** `py -3 scripts/test_platform_graph_runtime.py -v` Expected: PASS。不要跑真实 Omni。

---

### Task 12: Playwright 收口 + 验收文档

**Files:**
- Modify: `hmi/frontend/e2e/platform-dtype-editor.spec.ts`
- Create: `project-management/acceptance/UI-DTYPE-DAG-CANVAS.md`
- Modify: `project-management/CURRENT.md`, `tracking.csv`, `progress-board.md`, `changelog-progress.md`

**A-E2E 必须：**

1. 新建页 `dag-canvas` 可见；`palette-op-if` 可点出 if 节点
2. `dag-node-label` 存在且无删除按钮
3. `overview-locked-labels_tree` 存在；`overview-remove-labels_tree` 为 0
4. `dag-cloud-hint` 文案含 `本地按图执行；上云只跑公共前缀。`
5. 保存 draft 成功

**A 单测：** `test_platform_recipe_graph.py` + `test_platform_graph_runtime.py` + 既有 editor 套件。

- [ ] **Step 1: Run e2e**

working_directory: `hmi/frontend`  
`cmd /c "npx.cmd playwright test e2e/platform-dtype-editor.spec.ts"`

- [ ] **Step 2: Write acceptance** with sections **A** (commands + pass counts), **A-E2E** (playwright), **H** only if someone visually signed the canvas.

- [ ] **Step 3: Progress 四件套** — 本工单 status 按切片：A–C 可先标部分完成；整单 done 仅当 D 的 runtime 单测也过。若 Task 11 只落地 guard + source-kind if，在 acceptance 写明「ASR/标签 if 本地仍 RuntimeError，符合计划 Task 11 护栏」。

---

## Spec coverage

| Spec | Task |
|------|------|
| D1–D2 本地真 DAG / 不上云图执行 | 10–11 |
| D3 / D8 表达式 | 2 |
| D4 / §7 橱窗 + 锁树 | 5, 9 |
| D5 打标后节点 | 1, 10 |
| D6 / §6 投影压扁 | 4, 5 |
| D7 互斥汇合 | 1, 10 |
| D9 graph 权威 | 5 |
| D10 黄警告仍可 publish | 8 |
| D11 xyflow | 7 |
| ivi 补打标器 | 3, 5 |
| 无 graph 旧路径 | 11 |
| 不改 DataWorks | Global Constraints |
| Playwright | 7, 9, 12 |

## Placeholder / 一致性

- `_require_any_kinds_from_slots` 若为 private：在 `recipe_graph.py` 复制或改为公开，不要留「类似 Task N」
- `_chain()` 的 `op_id` 必须改成 `OPERATORS` 里真实 id（实现时打开 `operators.py` 选一个 preprocess）
- `pin_label_last` 不再把 label 挪到最后，与 D5 一致
- 前端没有 vitest：内核行为以后端单测为准；UI 用 Playwright
