# Augmentation Recipe Schema（扩增配方契约）

| 字段 | 值 |
|------|-----|
| recipe_schema_version | **1.0** |
| 维护 | M8.1；与 `aug_recipe.spec_json` 同步 |
| 执行 | **平台外** — 见 `examples/apply_aug_recipe.py` |

> 平台只**存储、版本化、挂载** recipe；不在 HMI/OSS 内执行 transform。

---

## 1. 顶层结构

```yaml
recipe_schema_version: "1.0"
recipe_code: multimodal_v1
version: 1
description: "OMS clip 多模态训练侧参考配方"
applies_to:
  export_preset: full          # minimal 仅 embedding 路径，recipe 无媒体可读
  modalities: [camera, audio]
transforms:
  - id: hflip_front
    type: horizontal_flip
    p: 0.5
    targets:
      - modality: camera
        cameras: [front, front_narrow]
  - id: time_jitter
    type: time_shift_ms
    p: 0.3
    params:
      range: [-200, 200]
    targets:
      - modality: audio
seed_policy:
  mode: per_epoch              # per_epoch | per_sample — 训练侧解释
  base_seed: 42
```

---

## 2. `transforms[]` 字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| id | string | ✓ | 配方内唯一 |
| type | string | ✓ | 见 §3 内建类型 |
| p | float | | 应用概率 [0,1] |
| params | object | | 类型相关参数 |
| targets | array | ✓ | 作用模态 |

### `targets[]`

| 字段 | 说明 |
|------|------|
| modality | `camera` \| `audio` \| `all` |
| cameras | camera 名列表（modality=camera 时） |

---

## 3. 内建 `type`（v1.0 参考集）

训练侧应实现；平台不校验运行时是否实现。

| type | 说明 | 典型 params |
|------|------|-------------|
| `horizontal_flip` | 图像水平翻转 | — |
| `vertical_flip` | 图像垂直翻转 | — |
| `random_crop` | 随机裁剪 | `scale`, `ratio` |
| `color_jitter` | 亮度/对比度 | `brightness`, `contrast`, `saturation` |
| `time_shift_ms` | 音频/时间轴平移 | `range: [min, max]` |
| `gain_db` | 音量增益 | `range: [min, max]` |
| `modality_dropout` | 随机丢弃某模态 | `drop_prob` |

**扩展**：自定义 `type` 允许，但须在 `description` 注明训练侧实现依赖。

---

## 4. 与 snapshot 的关系

| 挂载方式 | meta 字段 | 行级影响 |
|----------|-----------|----------|
| 仅 oversample | `augmentation_mode: oversample_only` | 虚拟行 + `aug_hint` |
| recipe 挂载 | `augmentation_mode: recipe_attached` | 所有行共享同一 recipe；transform 训练时应用 |
| 二者兼有 | `oversample_only` + recipe | 虚拟行 + recipe |

**y_json**：任何 transform **不得**改变 clip 级 taxonomy 标签（R2 / D-M8-2）。

---

## 5. 版本与发布

| status | 说明 |
|--------|------|
| draft | 可编辑 |
| published | 不可原地改；须 clone 升 version |
| archived | 不可挂到新 snapshot |

---

## 6. 示例（JSON 等价）

```json
{
  "recipe_schema_version": "1.0",
  "recipe_code": "embedding_probe_v1",
  "version": 1,
  "description": "embedding 探针无 transform；占位 recipe",
  "applies_to": { "export_preset": "minimal", "modalities": [] },
  "transforms": [],
  "seed_policy": { "mode": "per_epoch", "base_seed": 0 }
}
```

---

## 7. 相关文档

- M8 实现：`docs/m8-implementation-notes.md`
- Dataset 交付：`docs/dataset-delivery-schema.md`
