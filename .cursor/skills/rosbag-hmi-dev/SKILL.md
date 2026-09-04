---
name: rosbag-hmi-dev
description: >
  修改本仓库 HMI（FastAPI + React）时使用：路由、local/cloud 数据源、校核、Taxonomy Hub、
  Dataset、时间轴性能、Playwright A-E2E。不适用于：DataWorks 节点、MC DDL、ossutil 验数、
  只改 piplinesdk 算法。
---

# HMI 开发

栈：后端 `hmi/backend` `py -3 run.py` → `:8000`；前端 `hmi/frontend` **`npm.cmd run dev`** → **`:5174`**（`.env.development`），代理 `/api`。Windows 禁止直接 `npm`（拦 `npm.ps1`）。

## Gotchas

1. **PowerShell 直接 `npm`/`npx`** — 本机 ExecutionPolicy 拦 `npm.ps1`。**纠正：第一次就用 `npm.cmd` 或 `cmd /c`，见 alwaysApply `windows-powershell-npm.mdc`。**
2. **8000 上是旧 health（无 data_source）** — Windows 残留另一套 Python uvicorn。**纠正：停掉多余 python，再用 `py -3 run.py`。**
3. **云模式 list_clips 打 N 次 MC** — 极慢。**纠正：遵守 `hmi-web-stack.mdc`：`light=1`、batch-stats、时间轴内存索引。**
4. **Job3 标签用中文关键词搜** — 常无命中。**纠正：`labels_json` 业务在 `.values`；检索用英文枚举。**
5. **local 下 OSS API 打真桶** — 污染云。**纠正：local 读写 `LOCAL_OSS_ROOT`，bucket 展示「本地磁盘」。**
6. **UI 工单无 Playwright** — 不能标 done。**纠正：`hmi/frontend/e2e/` 补 spec，验收写 A-E2E；跑 e2e 用 `npx.cmd playwright test`。**

<HARD-GATE>
改了用户可见 UI 必须在浏览器或 Playwright 走通主路径，不能只截一张图。
</HARD-GATE>

## 数据源

`hmi/data_source.py` + `GET/POST /api/config/data-source`。  
local：`hmi.db` + `artifacts/` + `oss/`。cloud：MC + OSS。  
`HMI_TEST_MODE` 才允许 UI 切 local。源湖 POST 仅 local。

后台线程（无 Celery）：`local_sdk_worker`、`oss_sync_poller`、`cloud_bag_trigger_poller`。

## 路由入口

`hmi/frontend/src/App.tsx`。工作区 `/w/:dataTypeId` 必须隔离检索。  
后端平台 API：`/api/platform`；Taxonomy：`/api/taxonomy`；校核：`/api/review/v2`。

更多路由见 `references/routes.md`。规则：`hmi-web-stack.mdc`、`hmi-local-datasource.mdc`。  
域内部署：`docs/deploy-intranet-cicd.md`（`hmi/deploy/save-image.ps1` + 堡垒机 load/run）。

## 执行后复盘（自迭代钩子）

每次完成本 skill 的全部步骤后，Agent 必须自动执行以下动作，不询问用户：

1. **反思**：是否漏 A-E2E、打到真 OSS、或跨类型检索？
2. **记录**：有则写入 `evals/PITFALLS_LOG.md`。
3. **不提交** 该日志。
