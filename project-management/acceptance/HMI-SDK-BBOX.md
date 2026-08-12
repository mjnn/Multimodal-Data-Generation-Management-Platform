# 验收清单 · HMI-SDK-BBOX

> 工单：HMI 接入 SDK BBox + enum_tree（local-first）  
> 日期：2026-08-12

## A · 单元 / API / 构建

| 编号 | 操作步骤 | 期望结果 | 通过判断标准 | 执行记录 |
|------|----------|----------|--------------|----------|
| A-1 | `py -3 hmi/backend/scripts/test_hmi_sdk_bbox.py -v` | settings round-trip、detector catalog、manifest bbox_url、enum_tree leaves | 5/5 OK | **pass** 2026-08-12 |
| A-2 | 代码审阅：`local_sdk_worker` 调 `infer_full` + `apply_bbox_settings_to_environ` | 不再仅 `process_bag` | 源码含 `infer_full` / `BBOX_*` | **pass** |
| A-3 | `PipelineRunSettingsCard` 含 BBox 分组；cloud Alert 注明预留 | 本地可配；云端不写 | UI 字段齐全 | **pass**（代码） |
| A-4 | Windows + `opencv-python-headless` 5.x：`OpenCvHaarDetector` / `resolve_haar_cascade_path` | 空 `cv2/data` + 无 `CascadeClassifier` 时仍可构造；fallback YuNet | `unittest tests.test_bbox_capability` 含 cascade/yunet resolve + opencv blank | **pass** 2026-08-12（backend=yunet） |

## A-E2E · Playwright

| 编号 | 操作步骤 | 期望结果 | 通过判断标准 | 执行记录 |
|------|----------|----------|--------------|----------|
| A-E2E-1 | `hmi/frontend/e2e/pipeline-bbox-settings.spec.ts`：登录 → `/pipeline` | 可见「BBox 检测 / 预览编码」 | 断言通过 | **pending 环境**（需本地 HMI+认证；脚本已入库） |
| A-E2E-2 | Explorer：有 `bbox_url` 的 clip 显示 Plain\|BBox；无则隐藏 | `data-testid=preview-variant-toggle` | 需本地 stub 跑通产物 | **pending 数据**（H） |

## H · 人工

| 编号 | 摘要 |
|------|------|
| H-1 | 本地开 `bbox_enabled=stub` 跑一轮 bag，Explorer 切换 Plain/BBox 主观确认 |
| H-2 | Taxonomy Hub 新建 `enum_tree` 叶子：用输入框 +「深层嵌套」开关建树（不再贴 JSON），详情树展示嵌套不丢数据 |

## 范围说明

- **做了**：local 执行参数、worker `infer_full`、preview `cameras_bbox`、Explorer 切换、Hub enum_tree
- **补丁（2026-08-12）**：OpenCV 5 headless 无 Haar XML / 无 `CascadeClassifier` → SDK 打包 cascade+YuNet，自动选 Haar(cv2<5) 或 FaceDetectorYN(cv2≥5)
- **未做**：DataWorks bbox 参数、cloud OSS bbox 列举、canvas 叠框、HMI 在线 MC（仍为 CURRENT 推荐下一工单）
