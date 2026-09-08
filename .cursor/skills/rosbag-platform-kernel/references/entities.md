# 平台内核实体与 API 速查

## REST（`hmi/backend/hmi/platform/router.py`）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/platform/operators` | 算子目录（含 `role=stage` 的 label/embed、端口、`type_provides`、`source_kinds` 后缀列表） |
| GET/PUT | `/api/platform/data-types` `{id}` | 配方 |
| GET/POST | `/api/platform/sources` | 源湖；POST 仅 local |
| POST | `/api/platform/samples` | 高级/内部 |
| POST | `/api/platform/runs/preflight` | 预检；可 `assignments` |
| POST | `/api/platform/runs` | 开跑；单 slot 可裸 `source_ids`；多 slot 必须 `assignments: [{slot_id, source_ids}]` |
| POST | `/api/platform/products/lookup` | 产物缓存 |
| GET | `/api/platform/lineage` | `source_id` 或 `product_key` |

## 种子配方 slots（勿随意删）

见 `recipe.py` 内 `seed_recipes`：`oms_cabin` 多路相机+音频；`audio_array_spec` 阵列+HEAD.dat；`ivi_ui_stub` 画面占位；`audio_defect` 单路 wav + 布尔「是否有问题音频」（draft `audio_defect-v1`）。梅尔/SPL 运行时解码 PCM `.wav` 或 HEAD `.dat`；`parse_head_dat` 仍只要 `.dat`。

## 源 kind

`platform_source.kind` 与槽位 `kinds` 都是入湖文件后缀（`.bag` `.mp4` `.wav` `.jpg`…），不是泛型 `video`/`audio`。入库优先文件名后缀；旧值读时归一。`parse_bag` 产出勾选 **连续帧** / `.wav` / `.json`（画面是抽帧，不是成片 `.mp4`）。见 `hmi/platform/file_kinds.py`。

## 相关验收

`acceptance/PLAT-DTYPE-KERNEL.md`、`PLAT-DTYPE-LAKE.md`、`PLAT-LAKE-RUN-BIND.md`、`PLAT-PRODUCT-LINEAGE.md`、`UI-DTYPE-EDITOR.md`、`UI-DTYPE-SOURCE-NODES.md`、`PLAT-AUDIO-AST-LABEL.md`。
