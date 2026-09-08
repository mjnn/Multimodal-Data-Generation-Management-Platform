# Atomic Overview Layout Implementation Plan

> **Status (2026-09-08):** Tasks 1–6 complete. Playwright `platform-dtype-editor` + `nvh-label-tree` + `audio-defect-label-tree` **18/18**.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace composite overview widgets (`nvh_spectrum`, `cabin_multicam`) with atomic cards bound to named channel ports (`ch1`…`chN`) expanded from `channel_count`.

**Architecture:** Catalog operators declare `expand_outputs_from: "channel_count"` plus a template output port. `expand_output_ports(op, params)` turns that into `ch1`…`chN` with optional `port_titles`. Disk artifacts stay one multi-channel file; the UI slices `channels[K-1]`. Clip explorer renders `overview.detail` in order. Cards with the same `sync_group` share seek.

**Tech Stack:** FastAPI HMI (`hmi/backend/hmi/platform/`), React (`hmi/frontend`), unittest `py -3 hmi/backend/scripts/test_*.py`, Playwright `npx.cmd playwright test`.

## Global Constraints

- Do not change DataWorks nodes or Job order.
- Do not publish `audio_nvh-v2`.
- Do not copy Mel/SPL artifacts per channel.
- Do not auto-infer N from wav; N is only `params.channel_count` (1–16).
- Do not wrap cards in a nested sync-group container; use optional `sync_group` string on each card.
- Windows: `npm.cmd` / `npx.cmd`, never bare `npm`.
- Do not git commit unless the user explicitly asks.
- Do not click 「重置测试数据」 unless the user asks.
- Spec: `docs/superpowers/specs/2026-09-08-atomic-overview-layout-design.md`.

---

### Task 1: Expand output ports from `channel_count`

**Files:**
- Modify: `hmi/backend/hmi/platform/recipe_pipeline.py` (next to `output_ports`)
- Modify: `hmi/backend/hmi/platform/operators.py` (`_op` + audio ops)
- Test: `hmi/backend/scripts/test_expand_output_ports.py` (create)

**Interfaces:**
- Consumes: existing `output_ports(op) -> list[dict]`
- Produces:
  - `channel_count_from_params(params: dict | None) -> int`
  - `expand_output_ports(op: dict | None, params: dict | None = None) -> list[dict]`
  - Operator field `expand_outputs_from` optional, value `"channel_count"`

- [ ] **Step 1: Write the failing test**

Create `hmi/backend/scripts/test_expand_output_ports.py`:

```python
"""channel_count expands catalog template ports into ch1..chN."""
from __future__ import annotations
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "hmi" / "backend"))
sys.path.insert(0, str(REPO / "shared"))


class TestExpandOutputPorts(unittest.TestCase):
    def test_no_expand_returns_template(self) -> None:
        from hmi.platform.recipe_pipeline import expand_output_ports
        op = {"output_ports": [{"id": "out", "types": ["asr_jsonl"], "title": "转写"}]}
        ports = expand_output_ports(op, {"channel_count": 4})
        self.assertEqual([p["id"] for p in ports], ["out"])

    def test_channel_count_four_named(self) -> None:
        from hmi.platform.recipe_pipeline import expand_output_ports
        op = {
            "expand_outputs_from": "channel_count",
            "output_ports": [{"id": "out", "types": ["mel_matrix"], "title": "梅尔频谱"}],
        }
        ports = expand_output_ports(
            op,
            {"channel_count": 4, "port_titles": {"ch2": "驾驶位"}},
        )
        self.assertEqual([p["id"] for p in ports], ["ch1", "ch2", "ch3", "ch4"])
        self.assertEqual([p["channel_index"] for p in ports], [0, 1, 2, 3])
        self.assertEqual(ports[0]["types"], ["mel_matrix"])
        self.assertEqual(ports[1]["title"], "驾驶位")
        self.assertIn("梅尔", ports[0]["title"])

    def test_clamp_and_default(self) -> None:
        from hmi.platform.recipe_pipeline import channel_count_from_params
        self.assertEqual(channel_count_from_params(None), 1)
        self.assertEqual(channel_count_from_params({"channel_count": 0}), 1)
        self.assertEqual(channel_count_from_params({"channel_count": 99}), 16)
        self.assertEqual(channel_count_from_params({"channel_count": "3"}), 3)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3 hmi/backend/scripts/test_expand_output_ports.py`

Expected: FAIL `ImportError` for `expand_output_ports`.

- [ ] **Step 3: Write minimal implementation**

In `recipe_pipeline.py` after `output_ports`:

```python
MAX_CHANNEL_COUNT = 16


def channel_count_from_params(params: dict[str, Any] | None) -> int:
    raw = (params or {}).get("channel_count", 1)
    try:
        n = int(raw)
    except (TypeError, ValueError):
        n = 1
    return max(1, min(MAX_CHANNEL_COUNT, n))


def expand_output_ports(op: dict[str, Any] | None, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    template_ports = output_ports(op)
    if not op or str(op.get("expand_outputs_from") or "") != "channel_count":
        return template_ports
    template = dict(template_ports[0]) if template_ports else {"id": "out", "types": []}
    types = list(template.get("types") or [])
    base_title = str(template.get("title") or "").strip()
    titles = params.get("port_titles") if isinstance(params, dict) else None
    if not isinstance(titles, dict):
        titles = {}
    n = channel_count_from_params(params)
    out: list[dict[str, Any]] = []
    for i in range(1, n + 1):
        pid = f"ch{i}"
        custom = str(titles.get(pid) or "").strip()
        title = custom or (f"{base_title} {i}" if base_title else pid)
        port = dict(template)
        port["id"] = pid
        port["types"] = types
        port["title"] = title
        port["channel_index"] = i - 1
        out.append(port)
    return out
```

In `operators.py`, add `expand_outputs_from: str | None = None` to `_op` and copy it onto the dict when set. Set `expand_outputs_from="channel_count"` and add to `params_schema`:

```python
"channel_count": {"type": "integer", "minimum": 1, "maximum": 16},
"port_titles": {"type": "object"},
```

on `mel_spectrogram`, `stft_spectrogram`, `spl_timeline`, `third_octave`, `encode_preview`.

- [ ] **Step 4: Re-run tests**

Run: `py -3 hmi/backend/scripts/test_expand_output_ports.py`

Expected: `OK` (3 tests).

---

### Task 2: I/O contract + frontend port helper use expanded ports

**Files:**
- Modify: `hmi/backend/hmi/platform/io_contract.py` (`allowed_output_ids`)
- Modify: `hmi/frontend/src/utils/recipePipeline.ts` (`outputPorts`, `bindingOptions`)
- Modify: `hmi/frontend/src/api/types.ts` (`PlatformOperator.expand_outputs_from`, `ViewCard.sync_group`, `OperatorPort.channel_index`)
- Test: extend `hmi/backend/scripts/test_expand_output_ports.py`
- Test: `hmi/backend/scripts/test_io_contract.py` only if an existing assertion lists a single `out` for mel.

**Interfaces:**
- Consumes: `expand_output_ports(op, node.get("params"))`
- Produces: `allowed_output_ids` includes `ch1` when `channel_count=2`; frontend `expandOutputPorts(op, params)` / `outputPorts(op, params?)`

- [ ] **Step 1: Failing test** — add to `test_expand_output_ports.py`:

```python
    def test_allowed_output_ids_uses_expanded_ports(self) -> None:
        from hmi.platform.io_contract import allowed_output_ids
        from hmi.platform.operators import OPERATORS
        node = {
            "op_id": "mel_spectrogram",
            "params": {"channel_count": 2, "port_titles": {"ch1": "FL"}},
        }
        ids = allowed_output_ids(node)
        self.assertIn("ch1", ids)
        self.assertIn("ch2", ids)
```

- [ ] **Step 2: Run** `py -3 hmi/backend/scripts/test_expand_output_ports.py` — expect FAIL until `allowed_output_ids` uses expand.

- [ ] **Step 3: Implementation**

`io_contract.py` `allowed_output_ids`:

```python
from hmi.platform.recipe_pipeline import expand_output_ports
...
    for port in expand_output_ports(op, node.get("params") if isinstance(node.get("params"), dict) else {}):
```

Frontend `recipePipeline.ts`:

```ts
export function channelCountFromParams(params?: Record<string, unknown> | null): number {
  const raw = params?.channel_count ?? 1
  const n = typeof raw === 'number' ? raw : Number(raw)
  if (!Number.isFinite(n)) return 1
  return Math.max(1, Math.min(16, Math.trunc(n)))
}

export function expandOutputPorts(
  op: PlatformOperator | undefined,
  params?: Record<string, unknown> | null,
): OperatorPort[] {
  const template = outputPorts(op)
  if (!op || op.expand_outputs_from !== 'channel_count') return template
  const t0 = template[0] || { id: 'out', types: [] }
  const titles = (params?.port_titles && typeof params.port_titles === 'object' && !Array.isArray(params.port_titles)
    ? (params.port_titles as Record<string, unknown>)
    : {})
  const n = channelCountFromParams(params)
  const baseTitle = String(t0.title || '').trim()
  const out: OperatorPort[] = []
  for (let i = 1; i <= n; i += 1) {
    const id = `ch${i}`
    const custom = String(titles[id] ?? '').trim()
    out.push({
      ...t0,
      id,
      types: [...(t0.types || [])],
      title: custom || (baseTitle ? `${baseTitle} ${i}` : id),
      channel_index: i - 1,
    })
  }
  return out
}
```

Change `outputPorts` callers that inspect a **node** (inspector, DAG edges, `bindingOptions`) to `expandOutputPorts(op, card.params)`.

Fix `bindingOptions` upstream loop: iterate `expandOutputPorts(op, card.params)` and set `port_id: port.id` (e.g. `ch1`), match `neededTypes` against `port.types`. Label: `${op.title} · ${port.title}`.

Add types:

```ts
expand_outputs_from?: 'channel_count'
// OperatorPort
channel_index?: number
title?: string
// ViewCard
sync_group?: string
```

- [ ] **Step 4: Re-run** `py -3 hmi/backend/scripts/test_expand_output_ports.py` — OK.

---

### Task 3: Atomic view widgets; drop composite presets

**Files:**
- Modify: `hmi/backend/hmi/platform/views.py`
- Modify: `hmi/backend/hmi/platform/recipe.py` (`overview_view` validation)
- Modify: `hmi/frontend/src/utils/overviewLayout.ts`
- Test: `hmi/backend/scripts/test_audio_nvh_view.py`
- Test: `hmi/backend/scripts/test_platform_datatype_kernel.py` (overview_view / nvh_spectrum assertions)
- Test: `hmi/backend/scripts/test_platform_datatype_editor.py` (replace preset ids)

**Interfaces:**
- Consumes: none from Task 1 except widget ids used later in seeds
- Produces: widgets `spectrum_timeline`, `video_timeline`; `overview_view` allowed `{custom}` plus leftover ids only if hydrate ignores them; **no** `nvh_spectrum` / `cabin_multicam` in `VIEW_WIDGETS`

- [ ] **Step 1: Failing tests**

In `test_audio_nvh_view.py` change `test_view_and_recipe` to:

```python
        from hmi.platform.views import VIEW_WIDGET_IDS, VIEW_TEMPLATE_IDS
        self.assertIn("spectrum_timeline", VIEW_WIDGET_IDS)
        self.assertIn("video_timeline", VIEW_WIDGET_IDS)
        self.assertIn("labels_tree", VIEW_WIDGET_IDS)
        self.assertNotIn("nvh_spectrum", VIEW_WIDGET_IDS)
        self.assertNotIn("cabin_multicam", VIEW_WIDGET_IDS)
        self.assertEqual(VIEW_TEMPLATE_IDS, frozenset({"custom"}))
```

Add in a small test or same file:

```python
        from hmi.platform.views import hydrate_overview
        ov = hydrate_overview({"overview_view": "custom"})
        self.assertEqual(ov["detail"], [])
        with self.assertRaises(ValueError):
            hydrate_overview({"overview": {"detail": [{"widget_id": "nvh_spectrum"}]}})
```

Run: `py -3 hmi/backend/scripts/test_audio_nvh_view.py` — FAIL until views.py changes.

- [ ] **Step 2: Implement `views.py`**

- `VIEW_TEMPLATES = {"custom": {"id": "custom", "title": "自定义展示页", "description": "按原子组件拼版"}}`
- Delete `PRESET_LAYOUTS` entries for cabin/nvh/audio_spec or make them unused; `hydrate_overview` if no lists → `{preset: "custom", list: [], detail: []}` (do **not** fill from old presets).
- Remove widgets `nvh_spectrum`, `cabin_multicam`.
- Add:

```python
    "spectrum_timeline": {
        "id": "spectrum_timeline",
        "surface": "detail",
        "title": "频谱时间轴",
        "description": "单路梅尔或 STFT + 该路波形/SPL",
        "needs": ["mel_matrix", "stft_matrix"],
    },
    "video_timeline": {
        "id": "video_timeline",
        "surface": "detail",
        "title": "视频时间轴",
        "description": "单路预览画面",
        "needs": ["preview_mp4", "frames"],
    },
```

- `_normalize_card` also copies `sync_group` if non-empty string.
- `recipe.py` `overview_view` must be in `VIEW_TEMPLATE_IDS` (`custom`). Old `"cabin_timeline"` on **tests** must be updated to `"custom"` (those tests are Task 3/4). Saving a recipe with unknown widget still 400.

- [ ] **Step 3: Frontend `overviewLayout.ts`**

`FALLBACK_PRESETS` only `custom: { list: [], detail: [] }`. `hydrateOverview` with no lists returns empty detail. Remove `nvh_spectrum` from fallbacks.

- [ ] **Step 4: Fix kernel/editor unit tests** that still expect `nvh_spectrum` or `audio_nvh_timeline` — change to `spectrum_timeline` / `custom`. Run:

`py -3 hmi/backend/scripts/test_audio_nvh_view.py`

`py -3 hmi/backend/scripts/test_platform_datatype_kernel.py`

`py -3 hmi/backend/scripts/test_platform_datatype_editor.py`

Expected: OK after test fixtures use `overview_view: "custom"` and valid widgets.

---

### Task 4: Seed recipes + editor palette (no template dropdown)

**Files:**
- Modify: `hmi/backend/hmi/platform/recipe.py` (`SEED_RECIPES` graphs params + overview.detail)
- Modify: `hmi/frontend/src/pages/DataTypeEditorPage.tsx`
- Modify: `hmi/frontend/src/components/datatype/OverviewComposer.tsx` (unhide `labels_tree`, `sync_group` input)
- Modify: `hmi/frontend/src/components/datatype/DagNodeInspector.tsx` (channel_count + port titles)
- Test: `hmi/backend/scripts/test_platform_datatype_kernel.py` seed overview assertions
- E2E later in Task 6; here unittest seeds.

**Interfaces:**
- Consumes: widget ids from Task 3; `channel_count` / `port_titles` from Task 1
- Produces: seeds as in spec §7

- [ ] **Step 1: Failing seed assertions** in `test_platform_datatype_kernel.py` (replace nvh_spectrum checks):

```python
        nvh = seeds["audio_array_spec"]["overview"]["detail"]
        self.assertEqual(
            [c["widget_id"] for c in nvh],
            ["spectrum_timeline"] * 4 + ["labels_tree"],
        )
        self.assertEqual(seeds["audio_array_spec"]["overview_view"], "custom")
        mel = next(n for n in seeds["audio_array_spec"]["graph"]["nodes"] if n["key"] == "mel_spectrogram")
        self.assertEqual(int(mel["params"]["channel_count"]), 4)
```

- [ ] **Step 2: Run** — FAIL until seeds change.

- [ ] **Step 3: Seed patches**

Helper for four spectrum cards:

```python
def _spectrum_cards(step_key: str, n: int, sync: str) -> list[dict[str, Any]]:
    return [
        {
            "key": f"detail-spectrum-ch{i}",
            "widget_id": "spectrum_timeline",
            "sync_group": sync,
            "bindings": {
                "in": {"kind": "upstream", "step_key": step_key, "port_id": f"ch{i}"}
            },
        }
        for i in range(1, n + 1)
    ]
```

- `audio_array_spec`: set `channel_count: 4` on `mel_spectrogram`, `stft_spectrogram`, `spl_timeline`, `third_octave`. overview `custom`, detail = four spectrum (bind mel `ch1..4`, sync_group `"nvh-main"`) + `{widget_id: labels_tree, key: detail-labels}`.
- `audio_defect`: `channel_count: 1` on mel+spl; detail = one spectrum + labels_tree.
- `oms_cabin`: `encode_preview` `channel_count: 4`; four `video_timeline` bind `encode_preview` `ch1..ch4` + `asr_panel` + `labels_tree`.
- `ivi_ui_stub`: `overview_view: custom`, detail `frame_gallery_bbox` + `labels_tree`.

- [ ] **Step 4: Editor UX**

- Remove Form item `overview_view` Select and `onValuesChange` `cardsFromPreset`.
- Default new recipe `overview_view: 'custom'`, `overview.detail: []`.
- `OverviewComposer`: delete `HIDDEN_PALETTE_WIDGETS` hide of `labels_tree`. On each card, Input `sync_group` (`data-testid="overview-sync-group"`), placeholder `留空则独立`.
- Binding Select: already uses `bindingOptions` after Task 2 (expanded ports).
- `DagNodeInspector`: if `op.expand_outputs_from === 'channel_count'`, show InputNumber 1–16 for `channel_count` and N inputs for `port_titles.chK` (`data-testid="node-channel-count"`).

- [ ] **Step 5: Run kernel seed test** — OK.

---

### Task 5: Clip page renders atomic cards + single-channel spectrum + sync

**Files:**
- Modify: `hmi/frontend/src/components/AudioNvhTimelinePanel.tsx` (optional `channelName` / `channelIndex`)
- Modify: `hmi/frontend/src/components/ClipMediaPanel.tsx`
- Modify: `hmi/frontend/src/pages/ClipExplorerPage.tsx`
- Modify: `hmi/frontend/src/components/ReviewClipMediaPanel.tsx`
- Modify: `hmi/frontend/src/components/ClipTimelinePanel.tsx` (optional `cameraIndex` or `cameraName` for one stream)
- Test: `hmi/frontend/e2e/audio-defect-label-tree.spec.ts`, `nvh-label-tree.spec.ts`, `platform-dtype-editor.spec.ts`

**Interfaces:**
- Consumes: `overview.detail` cards with `widget_id` / `bindings.in.port_id` / `sync_group`
- Produces: runtime testids `overview-runtime-spectrum_timeline`, `overview-runtime-labels_tree`, `overview-runtime-video_timeline`

- [ ] **Step 1: Single-channel panel**

Add props `channelIndex?: number` to `AudioNvhTimelinePanel`. If set, render only `boot.channels[channelIndex]` (or empty state 「本路无频谱」). If unset, keep current all-channels behavior for any leftover caller — ClipMediaPanel **must always pass** the index from `chK` → `K-1`.

Export `portIdToChannelIndex(portId: string): number | null` in `recipeTaxonomy.ts` or `overviewLayout.ts`: `ch12` → 11, else null.

- [ ] **Step 2: ClipMediaPanel**

Stop using `composed.includes('nvh_spectrum')`. Map each `detailWidgetIds` **card** — change prop from `string[]` to `ViewCard[]` (`detailCards`) so bindings/sync survive.

- `spectrum_timeline` → `AudioNvhTimelinePanel` with `channelIndex` from `bindings.in.port_id`, `testId={`overview-runtime-spectrum_timeline-${port}`}`
- `video_timeline` → `ClipTimelinePanel` filtered to one camera index
- `frame_gallery_bbox` → existing gallery
- Do **not** render labels/asr/json here (those are explorer sections)

Pass a shared `syncSeek` when `sync_group` matches other spectrum cards: lift cursor to `ClipExplorerPage` `Record<string, number>` keyed by sync_group.

- [ ] **Step 3: ClipExplorerPage**

- `detailCards = hydrateOverview(recipe).detail`
- Media: widgets in `{spectrum_timeline, video_timeline, frame_gallery_bbox}`
- Below media, map remaining cards:
  - `labels_tree` → `ClipLabelTreeView` in `data-testid="overview-runtime-labels_tree"` (keep `clip-bound-label-tree` on the same node for defect e2e)
  - `asr_panel` → existing ASR from `MomentDetailPanel` extract or timeline meta
  - `json_tree` → existing pre
- Delete `纯音频 NVH` shell and `audio-nvh-label-tree` wrapper.
- Taxonomy still `recipeUsesNvhTaxonomy(recipe)` for which tree to load; **not** inferred from spectrum widgets.

- [ ] **Step 4: ReviewClipMediaPanel** — same `detailCards` mapping; no `nvh_spectrum` branch.

---

### Task 6: Playwright A-E2E

**Files:**
- Modify: `hmi/frontend/e2e/platform-dtype-editor.spec.ts` (`overview-card-nvh_spectrum` → add `spectrum_timeline`, assert palette has no 「四通道频谱时间轴」)
- Modify: `hmi/frontend/e2e/nvh-label-tree.spec.ts` (labels tree testid)
- Modify: `hmi/frontend/e2e/audio-defect-label-tree.spec.ts` (already bound tree; assert no 纯音频 NVH; optional one spectrum card)
- Modify: `hmi/frontend/e2e/pipeline-datatype-run.spec.ts` / `platform-lake.spec.ts` if they mention nvh_spectrum

- [x] **Step 1: Update selectors**

Editor: `overview-add-spectrum_timeline`, `getByText('四通道频谱时间轴')` count 0.

NVH explorer: `getByTestId('overview-runtime-labels_tree')` visible; L6 `quick-review-nvh.sem.quality_grade` still works. Expand collapse as today.

Defect: `clip-bound-label-tree` / `overview-runtime-labels_tree`, no `纯音频 NVH`.

- [x] **Step 2: Run** (frontend dir):

```
cmd /c "npx.cmd playwright test e2e/audio-defect-label-tree.spec.ts e2e/nvh-label-tree.spec.ts e2e/platform-dtype-editor.spec.ts --reporter=list"
```

Need local FastAPI `:8000`. Use `npm.cmd` only via cmd.

Expected: pass. If editor spec still seeds old widget via API, PUT will 400 — the live DB recipe must be re-saved from seeds on backend **restart** (`_seed_builtin_data_types` overwrites builtins). Restart `py -3 run.py` after seed change.

---

## Spec coverage

| Spec | Task |
|------|------|
| D1 atomic palette / no presets | 3, 4 |
| D2 one-channel spectrum widget | 5 |
| D3 channel_count → chN | 1, 2, 4 |
| D4 no per-channel files | 1 (no kernel copy) |
| D5 sync_group | 4 UI + 5 runtime |
| D6 break old widgets / rewrite seeds | 3, 4 |
| D7 Clip 详情 = detail cards | 5 |
| encode_preview expand | 1 flag + 4 oms seed |
| A / A-E2E tests | 1–6 |

## Placeholder scan

No TBD. Commits omitted unless the user asks.
