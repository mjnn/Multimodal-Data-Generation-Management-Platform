# 项目交接说明书（人 + Agent）

> **日期**：2026-08-25  
> **对象**：接手开发的同事，或新会话里的 Cursor Agent  
> **权威链**：PRD > `docs/mN-implementation-notes.md` > `project-management/CURRENT.md`

本文件是交接**第一入口**。读完本节即可开工；细节跟链接走，不要在未读 `CURRENT.md` 时改业务代码。

---

## 30 秒定位

这是一个 **ROS bag 多模态数据平台** Monorepo：

1. **管线**：bag → OMS Multimodal SDK（`sdk_v1`）→ OSS + MaxCompute  
2. **HMI**：FastAPI + React，按 **DataType 配方** 做源湖 / 开跑 / 校核 / Dataset  
3. **云端**：阿里云 DataWorks + MaxFrame + DPE（新数据走 **单 Driver 节点**，不是旧 Job1–4）

当前产品重心是 **平台内核重构**（源湖 + DataType + 产物血缘），不是再扩 clip-omni v2。

---

## 新同事 / 新 Agent 必读顺序

| 顺序 | 文件 | 为什么 |
|------|------|--------|
| 1 | 本文件 + [`CURRENT.md`](../project-management/CURRENT.md) | 现在做什么、禁止抢跑 |
| 2 | [`WIKI.md`](WIKI.md) · [`architecture.md`](architecture.md) | 系统长什么样 |
| 3 | [`CODE_MAP.md`](CODE_MAP.md) | 改哪几个目录 |
| 4 | [`AGENTS.md`](../AGENTS.md) · [`acceptance/_FORMAT.md`](../project-management/acceptance/_FORMAT.md) | 工单怎么收工 |
| 5 | 按任务打开对应 Skill（见下） | 避免踩坑 |

**新会话口令（贴给 Agent）：**

```text
先读 docs/HANDOVER.md 与 project-management/CURRENT.md。
当前重点是平台内核，不要做 HMI 在线 H-2，不要 publish audio_nvh-v2，不要改 DataWorks。
按推荐下一个工单做；结束时回写进度四件套 + acceptance（A / A-E2E / H）。
```

---

## 当前进度（交接日快照）

以 `CURRENT.md` 为准；此处只作快照，过期以 CURRENT 为准。

| 项 | 值 |
|----|-----|
| 刚完成 | **PLAT-AUDIO-AST-LABEL**：阵列 L6 用 AST + AudioSet-527 填 category/sources |
| **推荐下一工单** | **UI-NVH-REVIEW-SAVE**（语义 L6 人工写回） |
| 暂停 | M9.3 H-2（HMI 在线主观）不排期 |
| 云端 SDK 全链 | M9.3 A-C 基本闭合；hybrid 4-bag `Summary: 18/18 passed` |

### 禁止抢跑（写代码前再看一遍）

- 勿 **publish** `audio_nvh-v2`（会 archive OMS 已发布树）
- 勿做 HMI 在线 **H-2**
- 勿宣称 IVI 业务打标已完成（`ivi_ui_stub` 仅占位）
- 勿用 VL 打 bbox（仅 opencv / yolo）
- 勿为新 bag 写 `parsed/aligned/ai` 或混写 `aig_rosbag__`
- 勿在 DPE UDF 里用 `@dataclass` / 自定义 class
- 检索禁止跨 DataType 混合命中

---

## 仓库地图

```text
rosbag_to_labels_pipline/
├── shared/                 # 全局配置：config.yaml、clip_id、路径常量、Taxonomy
├── piplinesdk/             # oms-multimodal-sdk（extract/asr/label/embed）
├── pipeline/               # DataWorks 节点、MC DDL、验数、本地 parse
├── hmi/                    # 校核 Web：backend FastAPI + frontend React
├── docs/                   # Wiki / PRD / 架构 / 本交接书
├── project-management/     # CURRENT、工单、acceptance
└── .cursor/                # rules + Agent skills（技能包）
```

完整树：[`REPO_LAYOUT.md`](REPO_LAYOUT.md)。

---

## 本地 10 分钟跑起来

```powershell
# 1. Python（HMI + 管线 + editable SDK）
cd hmi
py -3 -m pip install -r requirements-dev.txt

# 2. 环境（仓库根，勿提交）
copy ..\.env.example ..\.env
# 填 ODPS_* / OSS_*；SDK 打标还需 DASHSCOPE_*

# 3. 后端
cd backend
py -3 run.py          # http://127.0.0.1:8000

# 4. 前端（另开终端；PowerShell 必须用 .cmd，禁止直接 npm）
cd hmi\frontend
npm.cmd install
npm.cmd run dev       # http://127.0.0.1:5174 ，/api 代理到 8000

# 5. 导入样例（可选）
cd hmi
py -3 scripts\import_real_data_clips.py --source pipeline_latest --reset
```

首个管理员：`cd hmi && py -3 scripts/bootstrap_admin.py`。  
健康检查：`GET http://127.0.0.1:8000/api/health` 应含 `data_source`。

Windows 若 8000 像旧进程：先停掉残留 `python`，再用 `py -3 run.py`（见 `.cursor/rules/hmi-web-stack.mdc`）。  
PowerShell 会拦截 `npm.ps1`：用 `npm.cmd` / `npx.cmd`，不要改 ExecutionPolicy（见 `.cursor/rules/windows-powershell-npm.mdc`）。

---

## 三条数据路径（选错会改错代码）

| 路径 | 何时用 | 入口 |
|------|--------|------|
| **HMI 本地 SDK worker** | 日常开发、源湖开跑、NVH/AST | `hmi/backend/hmi/services/local_sdk_worker.py` |
| **云端 SDK v1（推荐新 bag）** | DataWorks 生产 | `pipeline/dataworks/bundled/sdk_pipeline_driver_node.py` |
| **Legacy Job0–4** | 只维护历史 clip-omni v2 | `pipeline/dataworks/job*_node.py` — **新数据禁止** |

OSS 新 run：`clips/{clip_id}/runs/{run_id}/`，`layout_version: sdk_v1`。  
MC 新表前缀：`aig_sdk__`。旧前缀 `aig_rosbag__` 勿混写。

---

## Agent 技能包（本仓库已内置）

安装位置：`.cursor/skills/`。新机器只要打开本仓库，Cursor 即可发现。

| Skill | 何时读 |
|-------|--------|
| `rosbag-onboarding` | **任何新会话 / 交接 / 不知道从哪下手** |
| `rosbag-platform-kernel` | DataType / 源湖 / Sample / Run / 血缘 |
| `rosbag-hmi-dev` | 改 HMI 前后端、路由、本地/云数据源 |
| `rosbag-sdk-pipeline` | SDK 阶段、DataWorks Driver、DPE、验数 |
| `cloud-cli-ops` | 本机 ossutil / odpscmd 查 OSS+MC（不触发 Job） |

打包副本与压缩包说明见仓库根 [`handover/README.md`](../handover/README.md)。

---

## 域内部署（堡垒机 POC）

完整步骤（Dockerfile、`docker save`、SFTP、`docker load` / `docker run` 参数）：

- Markdown：[`docs/deploy-intranet-cicd.md`](deploy-intranet-cicd.md)
- Word（给人打印/转发）：[`docs/多模态数据平台-域内部署指南.docx`](多模态数据平台-域内部署指南.docx)

开发机在仓库根：

```powershell
powershell -File hmi\deploy\save-image.ps1 -Tag 20260827-1
sftp -P 60022 <堡垒机账号>@odnpgdcpiv.bastionhost.aliyuncs.com
```

堡垒机密码与 MFA **不要**写入本仓库，见交接 Word《域内服务器连接使用指南》或向 CI 申请。SSH 选中 **智能座舱POC** 后再 `docker load`。

---

## 收工检查单（每个工单）

1. 实现前读 CURRENT + 当前 Mn Notes  
2. 只做推荐工单，不静默连做多个  
3. 回写：CURRENT、`tracking.csv`（UTF-8 BOM）、progress-board、changelog  
4. 写 `project-management/acceptance/<工单ID>.md`（**A / A-E2E / H**）  
5. 聊天附 A + A-E2E 结果表；UI 可脚本化路径必须有 A-E2E，不要只写 H  

---

## 相关文档

| 文档 | 内容 |
|------|------|
| [`architecture.md`](architecture.md) | 架构图全集（系统 / 内核 / 云管线 / HMI / NVH） |
| [`deploy-intranet-cicd.md`](deploy-intranet-cicd.md) | 域内堡垒机 + docker save/load/run |
| [`WIKI.md`](WIKI.md) | 产品百科（能力、配置、API、脚本） |
| [`CODE_MAP.md`](CODE_MAP.md) | 中文代码导览（按目录注释职责） |
| [`prd-rosbag-labels.md`](prd-rosbag-labels.md) | 需求最高权威 |
| [`sdk-v1-cloud-e2e-runbook.md`](sdk-v1-cloud-e2e-runbook.md) | 上云 E2E |
| `docs/superpowers/specs/` | 平台内核 / AST / 单 Driver 设计规格 |
