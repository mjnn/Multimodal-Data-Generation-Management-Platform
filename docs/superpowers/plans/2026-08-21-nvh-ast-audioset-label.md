# NVH AST AudioSet Label Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Local `audio_array_spec` L6 uses YuanGongND AST + the existing AudioSet-527 `pytorch_model.bin` to fill `noise_category` / `noise_sources`; heuristic still fills grade/annoyance; hypothesis lists event names and scores.

**Architecture:** Vendor Gong `ASTModel` (no Dropbox download). Remap HuggingFace state dict (separate q/k/v → fused qkv). Kaldi 128-mel fbank at 16 kHz. Mix 4ch PCM to mono. Optional extra: torchaudio + timm==0.4.5. Missing deps/weights → heuristic fallback.

**Tech Stack:** Python 3.11, numpy, optional torch/torchaudio/timm, unittest.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-21-nvh-ast-audioset-label-design.md`
- Do not publish `audio_nvh-v2`
- Do not change DataWorks / MC
- Do not commit `pytorch_model.bin`
- Do not clobber `nvh.clip.*` / `nvh.ch.*`
- Default `hmi/backend/requirements.txt` stays without torchaudio/timm
- Do not commit unless the user asks

---

## File map

| Path | Responsibility |
|------|----------------|
| `hmi/backend/hmi/local/nvh_ast/labels.py` | 527 names + AudioSet→NVH map + top-k patch |
| `hmi/backend/hmi/local/nvh_ast/remap.py` | HF keys → ASTModel keys |
| `hmi/backend/hmi/local/nvh_ast/model.py` | Load ASTModel from remapped weights |
| `hmi/backend/hmi/local/nvh_ast/infer.py` | PCM → probs |
| `hmi/backend/hmi/local/nvh_ai_label.py` | `nvh_sem_ast` branch |
| `hmi/backend/hmi/platform/recipe.py` | seed model id |
| `hmi/backend/requirements-nvh-ast.txt` | optional torchaudio, timm==0.4.5 |
| `hmi/backend/scripts/test_nvh_ast_label.py` | unit tests |
| `.gitignore` | `hmi/data/models/` |

---

### Task 1: AudioSet → NVH mapping (no torch)

**Files:**
- Create: `hmi/backend/hmi/local/nvh_ast/__init__.py`
- Create: `hmi/backend/hmi/local/nvh_ast/labels.py`
- Test: `hmi/backend/scripts/test_nvh_ast_label.py`

**Interfaces:**
- Produces: `AUDIOSET_NAMES: list[str]` length 527, index 0 = `"Speech"`
- Produces: `map_audioset_topk(probs: list[float], *, k=5, min_score=0.05) -> dict` with keys `noise_category`, `noise_sources`, `topk` (`[{index,name,score}]`), `mapped`

- [ ] **Step 1: Write failing tests** `test_speech_is_index_0`, `test_engine_maps_category_and_source`, `test_unmapped_keeps_none_category`
- [ ] **Step 2: Implement `labels.py`**
- [ ] **Step 3: Run** `py -3 hmi/backend/scripts/test_nvh_ast_label.py -v` — Task 1 cases pass

---

### Task 2: HF → Gong remap

**Files:**
- Create: `hmi/backend/hmi/local/nvh_ast/remap.py`
- Test: `hmi/backend/scripts/test_nvh_ast_label.py`

**Interfaces:**
- Produces: `remap_hf_to_ast(state: dict) -> dict`

- [ ] **Step 1: Failing test** with tiny fake HF tensors: q/k/v (8,8) concat to qkv (24,8); cls_token → `v.cls_token`; classifier.dense → `mlp_head.1.weight`
- [ ] **Step 2: Implement remap**
- [ ] **Step 3: Tests pass**

---

### Task 3: `fill_nvh_semantic_labels` AST branch (mocked infer)

**Files:**
- Modify: `hmi/backend/hmi/local/nvh_ai_label.py`
- Modify: `hmi/backend/hmi/platform/recipe.py` seed model `nvh_sem_ast`
- Test: `hmi/backend/scripts/test_nvh_ast_label.py` + existing `test_nvh_ai_label.py` recipe assertion

- [ ] **Step 1: Failing test** mock `infer_audioset_probs` returning Engine-high vector; assert category=engine, quality_grade still heuristic, clip keys untouched, hypothesis contains `Engine=`
- [ ] **Step 2: Implement merge in `fill_nvh_semantic_labels`**
- [ ] **Step 3: Update seed recipe; fix `test_recipe_label_enabled`**
- [ ] **Step 4: Tests pass**

---

### Task 4: Optional real inference + fallback

**Files:**
- Create: `hmi/backend/hmi/local/nvh_ast/model.py` (vendor Gong ASTModel, strip wget)
- Create: `hmi/backend/hmi/local/nvh_ast/infer.py`
- Create: `hmi/backend/requirements-nvh-ast.txt`
- Modify: `.gitignore`

- [ ] **Step 1: Test fallback** when weights missing → `ai_mode=heuristic_fallback`
- [ ] **Step 2: Implement infer + load; copy weights locally if present**
- [ ] **Step 3: Tests pass without requiring timm in default env**

---

### Task 5: Progress writeback

- [ ] `project-management/acceptance/PLAT-AUDIO-AST-LABEL.md` with A table
- [ ] CURRENT / tracking / board / changelog
