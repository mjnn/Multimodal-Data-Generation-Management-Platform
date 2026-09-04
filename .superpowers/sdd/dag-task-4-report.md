# Task 4 Report: 图投影公共前缀

## Status: DONE

## TDD

### RED
```
py -3 scripts/test_platform_recipe_graph.py TestProjectGraph -v
ImportError: cannot import name 'project_graph' / 'graph_is_lossy'
FAILED (errors=2)
```

### GREEN
```
py -3 scripts/test_platform_recipe_graph.py -v
Ran 22 tests in 0.017s — OK
```

## Changes

| File | Change |
|------|--------|
| `hmi/backend/hmi/platform/recipe_graph.py` | Added `graph_is_lossy`, `_prefix_op_keys`, `project_graph`, local `_require_any_kinds_from_slots`; hydrate source nodes copy `kinds` / cardinality |
| `hmi/backend/scripts/test_platform_recipe_graph.py` | `TestProjectGraph` (2 cases); `_chain()` op_id → `transcribe` |

## Controller decisions applied

1. `_chain()` uses `transcribe` (present in `OPERATORS`); assertion expects `["transcribe"]`.
2. `_require_any_kinds_from_slots` duplicated in `recipe_graph.py` (uses public `singleton_kind_groups`).
3. Prefix algorithm: BFS marks then/else descendants blocked; embed → `stages.embed.enabled`; detect_bbox → `bbox.enabled`.
4. `hydrate_graph` source params include kinds/cardinality from step cards.

## Commits

None (per task instruction).

## Concerns

None. Task 5 roundtrip can rely on real `transcribe` op_id and hydrated source `params.kinds`.
