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

