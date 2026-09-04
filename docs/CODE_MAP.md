# 中文代码导览（CODE MAP）

> 给接手同事：先按目录找入口，再打开文件头注释。  
> **不要求**给全仓库每一行加注释；关键包已加模块级中文说明。改功能时优先读本表对应文件。

权威布局仍见 [`REPO_LAYOUT.md`](REPO_LAYOUT.md)。

---

## 1. 根与共享

| 路径 | 中文职责 |
|------|----------|
| `AGENTS.md` | Agent 开工/收工；权威链 PRD > Mn Notes > CURRENT |
| `README.md` | 仓库对外入口 |
| `docs/HANDOVER.md` | **交接第一入口** |
| `docs/deploy-intranet-cicd.md` | 域内 POC：save / sftp / load / run |
| `docs/WIKI.md` | 产品百科 |
| `docs/architecture.md` | 架构图 |
| `docs/prd-rosbag-labels.md` | 需求最高权威 |
| `shared/config.yaml` | OSS/MC/Job 单一配置源（路径/模型勿硬编码） |
| `shared/clip_id.py` | `clip_id = sha256:{bag 内容}`，与目录名无关 |
| `shared/repo_paths.py` | `REPO_ROOT` / `HMI_ROOT` / `PIPELINE_ROOT` / `.env` 路径 |
| `shared/cloud_config.py` | 读 YAML + 环境覆盖 |
| `shared/config/oms_label_taxonomy.yaml` | OMS 68 项 |
| `shared/config/audio_nvh_taxonomy.yaml` | 阵列 NVH 树（draft v2 勿 publish） |

---

## 2. HMI 后端 `hmi/backend/`

| 路径 | 中文职责 |
|------|----------|
| `run.py` | 启动 uvicorn `hmi.main:app` :8000 |
| `hmi/main.py` | FastAPI 应用：lifespan 启 poller、clips/oss/upload/health |
| `hmi/config.py` | Settings；加载仓库根 `.env` |
| `hmi/data_source.py` | **local / cloud** 切换；`LOCAL_ROOT` = hmi_runtime 或 hmi_local |
| `hmi/router.py` | 按数据源选择 `clips_svc` / `search_svc` |
| `hmi/app_db.py` | **app.db** schema（用户/taxonomy/review/dataset/platform） |
| `hmi/db.py` | 云端 ODPS 连接与缓存 |
| `hmi/auth/` | JWT、角色、`/api/auth` |
| `hmi/admin/` | 用户、审计、system-env |
| `hmi/platform/` | **平台内核 REST**：源湖、DataType、Run、血缘 |
| `hmi/platform/recipe.py` | 配方校验 + 内置 `oms_cabin` / `ivi_ui_stub` / `audio_array_spec` |
| `hmi/platform/store.py` | platform_* SQLite 持久化 |
| `hmi/platform/run_bind.py` | 多选源 → 自动 Sample+Run |
| `hmi/platform/operators.py` | 代码注册算子（parse_bag、mel、频谱等） |
| `hmi/taxonomy/` | M10 Hub：coverage/diff/impact/lineage/proposals |
| `hmi/review/` | 校核 v1/v2、派发、bbox-QA |
| `hmi/dataset/` | 数据集快照 / derive / export |
| `hmi/local/` | 本地管线执行、bag 上传、NVH、schema.sql |
| `hmi/local/nvh_ai_label.py` | L6：heuristic / **nvh_sem_ast** / VL |
| `hmi/local/nvh_ast/` | Gong AST + AudioSet-527 映射 |
| `hmi/local/nvh_deriver.py` | 客观指标 → L2 叶子 |
| `hmi/services/local_sdk_worker.py` | 扫本地 rosbags 队列跑 SDK 或阵列配方 |
| `hmi/services/oss_sync_poller.py` | 读 dispatch 同步产物 |
| `hmi/services/clips*.py` `search*.py` | cloud vs local 双实现 |
| `hmi/media/` | preview / bbox 文件服务 |

**改平台内核**：几乎总在 `hmi/platform/` + 前端 `pages/DataType*` / `Lake*` / `Pipeline*`。  
**改 NVH 打标**：`local/nvh_*`，不要改 `piplinesdk` 的 OMS label 阶段。  
**改云 Job**：`pipeline/dataworks/`，且当前工单明确禁止改 DataWorks 时不要动。

---

## 3. HMI 前端 `hmi/frontend/src/`

| 路径 | 中文职责 |
|------|----------|
| `App.tsx` | **路由表**（DataType 首页、工作区、源湖、管线、Taxonomy、校核、Dataset） |
| `api/` | HTTP 客户端与 TS 类型 |
| `auth/` | 登录态、角色门控 |
| `context/DataSourceModeContext.tsx` | 本地/在线模式 |
| `context/DataTypeWorkspaceContext.tsx` | 当前 DataType 工作区 |
| `pages/DataTypeHomePage.tsx` | `/` 类型卡片列表 |
| `pages/DataTypeEditorPage.tsx` | 新建/编辑配方（admin） |
| `pages/DataTypeWorkspaceLayout.tsx` | `/w/:dataTypeId` |
| `pages/OverviewPage.tsx` | 总览（舱内时间轴 / NVH 频谱） |
| `pages/LakeManagePage.tsx` | 源入库 + OSS Tab |
| `pages/PipelineManagePage.tsx` | 开跑、绑定、执行 |
| `pages/TaxonomyPage.tsx` | Hub + ContextBar + lineage |
| `pages/ClipExplorerPage.tsx` | 时间轴浏览（lazy） |
| `pages/ReviewWorkbenchPage.tsx` | 校核工作台 |
| `pages/DatasetListPage.tsx` | 数据集 |
| `e2e/*.spec.ts` | Playwright；UI 工单必须有 A-E2E |

默认 `npm run dev` → **5173**（可用 `VITE_DEV_PORT`）；代理 `/api` → `127.0.0.1:8000`。

### 3.1 部署 `hmi/deploy/`

| 路径 | 中文职责 |
|------|----------|
| `Dockerfile` | HMI 生产镜像；**仓库根** `docker build -f hmi/deploy/Dockerfile .` |
| `save-image.ps1` | 开发机 build + `docker save` 到 `offline/*.tar` |
| `compose.yaml` | 8012:8000 + volume |
| `ecs_rollout.sh` | 公网 ECS compose pull |
| `push-acr.ps1` | 推 ACR（域内 POC 一般不用） |
| `offline/README.md` | 某次 tar 的 load 示例 |

域内堡垒机全流程：`docs/deploy-intranet-cicd.md`。

---

## 4. SDK `piplinesdk/`

| 路径 | 中文职责 |
|------|----------|
| `oms_multimodal/cli.py` | `python -m oms_multimodal inspect/run` |
| `oms_multimodal/client.py` | `OmsMultimodalClient.process_bag` |
| `oms_multimodal/capabilities/stages.py` | 阶段顺序与别名 |
| `oms_multimodal/bbox/` | 本地检测；权重 gitignore |
| `docs/SDK.md` `DATAWORKS_SDK.md` | SDK 与上云说明 |

阶段：`ingest → extract → bbox → encode → asr → preview → label → embed → upload`。  
`MODEL_BACKEND=api`（本机百炼）或 `mc`（MaxFrame AI）。

---

## 5. 管线 `pipeline/`

| 路径 | 中文职责 |
|------|----------|
| `dataworks/sdk_pipeline_driver_node.py` | **生产源码**单 Driver |
| `dataworks/bundled/sdk_pipeline_driver_node.py` | **粘贴进 DataWorks 的整文件** |
| `dataworks/sdk_*_node.py` | 冻结的多节点 SDK，应急参考 |
| `dataworks/job0_*` … `job4_*` | Legacy clip-omni v2 |
| `sql/maxcompute/aig_sdk__ddl.sql` | 新表 |
| `sql/maxcompute/aig_rosbag__ddl.sql` | 旧表 |
| `scripts/bundle_sdk_pipeline_driver.py` | 生成 bundled |
| `scripts/check_dpe_nodes.py` | 扫描禁止 class |
| `scripts/verify_sdk_v1_run.py` | 云端 SDK 验数 |
| `scripts/ingest_sdk_run_to_mc.py` | 离线 run 入库 |
| `parse_rosbag.py` | 本地遗留 Job1 解析 |
| `docker/dpe-sdk-pack/` | SDK DPE 镜像 |

改节点后必须重新 bundle，粘贴 **bundled** 文件，不要只改 thin 源码。

---

## 6. 进度与验收 `project-management/`

| 路径 | 中文职责 |
|------|----------|
| `CURRENT.md` | 热指针、推荐下一工单、禁止项 |
| `tracking.csv` | 工单主数据，**UTF-8 BOM** |
| `progress-board.md` | Todo/Doing/Done |
| `changelog-progress.md` | 倒序变更 |
| `acceptance/_FORMAT.md` | A / A-E2E / H |
| `acceptance/<ID>.md` | 宣称 done 的凭证 |

---

## 7. 改代码时怎么选文件

| 你想… | 打开 |
|--------|------|
| 新 DataType 字段/校验 | `platform/recipe.py` + `DataTypeEditorPage.tsx` |
| 源湖上传 | `platform/router.py` + `local/source_upload.py` + `LakeManagePage` |
| 开跑绑定 | `platform/run_bind.py` + `LakeRunBindPanel` |
| AST 标签 | `local/nvh_ast/` + `nvh_ai_label.py` |
| 时间轴性能 | `services/clips_local.py` + `hmi-web-stack.mdc` |
| 上云 extract | `sdk_pipeline_driver_node.py` + DPE pickle 规则 |
| 域内部署 / docker save | `docs/deploy-intranet-cicd.md` + `hmi/deploy/save-image.ps1` |
