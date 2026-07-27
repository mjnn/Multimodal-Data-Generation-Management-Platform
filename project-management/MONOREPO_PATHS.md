# Monorepo 路径（2026-07 重组后）

工单 / acceptance 里若仍出现无前缀的 `backend/`、`scripts/`，以本表为准：

| 旧写法 | 现路径 |
|--------|--------|
| `backend/hmi/` | `hmi/backend/hmi/` |
| `backend/scripts/test_*.py` | `hmi/backend/scripts/test_*.py`（先 `cd hmi/backend`） |
| `scripts/sync_hmi_local.py` | `hmi/scripts/sync_hmi_local.py` |
| `scripts/import_real_data_clips.py` | `hmi/scripts/import_real_data_clips.py` |
| `scripts/verify_pipeline_run.py` | `pipeline/scripts/verify_pipeline_run.py` |
| `config.yaml` | `shared/config.yaml` |
| `dataworks/` | `pipeline/dataworks/` |

总览：**`docs/REPO_LAYOUT.md`**
