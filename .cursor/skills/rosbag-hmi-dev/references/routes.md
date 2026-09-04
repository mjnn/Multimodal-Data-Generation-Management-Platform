# HMI 路由与包

## 前端 `src/pages`

| 路由 | 页面 |
|------|------|
| `/` | DataTypeHomePage |
| `/data-types/new` `:id/edit` | DataTypeEditorPage（admin） |
| `/w/:dataTypeId` | OverviewPage |
| `/lake` | LakeManagePage（入库 + OSS） |
| `/pipeline` | PipelineManagePage |
| `/taxonomy` | TaxonomyPage |
| `/clips/:clipId` | ClipExplorerPage |
| `/review/*` | 校核工作台 / 派发 |
| `/datasets` | Dataset* |
| `/admin/*` | 用户 / 审计 / system-env |

## 后端包

`hmi/main.py` 装配路由；`platform/` 内核；`taxonomy/` M10；`review/` 校核；`dataset/` 导出；`local/` 本地执行与 NVH；`services/clips*.py` 双数据源。

## 库文件

- `hmi/data/app.db`：用户与平台表
- `hmi/data/hmi_runtime/hmi.db`：clip 事实表（`HMI_RUNTIME_ROOT`）
