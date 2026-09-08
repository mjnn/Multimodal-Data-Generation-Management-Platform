# Design: 展示页原子排版 + 多路命名输出口

> 日期：2026-09-08  
> 状态：approved（2026-09-08；实现计划 `docs/superpowers/plans/2026-09-08-atomic-overview-layout.md`）  
> 定位：展示页不再用「四通道频谱时间轴 / 舱内多路」整包组件；管线节点按通道数展开命名口，展示页逐张绑定。  
> 非目标：改 DataWorks；publish `audio_nvh-v2`；新频谱算法。

---

## 1. 已拍板

| ID | 决策 | 选择 |
|----|------|------|
| D1 | 复合组件 | **删除**。调色盘只留原子组件。无整页预设（舱内多模 / 四通道频谱 / 音频频谱+ASR）。 |
| D2 | 「频谱时间轴」粒度 | **一路**：该路的梅尔（或 STFT）+ 可选 SPL + 波形。不把三张图再拆成三个组件。拆的是通道，不是图种。 |
| D3 | 多路口怎么来 | 节点参数 **通道数 N**（1–16）→ 自动生成 N 个同类型输出口；检查器里可改每个口的显示名。 |
| D4 | 磁盘产物 | **仍一份**多通道矩阵 / jsonl。口是逻辑切片（`port_id` → channel index），不按通道复制文件。 |
| D5 | 时间轴同步 | 默认各卡独立播放头。展示卡可选填 **同步组 id**（同 id 共用 seek）。 |
| D6 | 旧配方 | **不兼容** `nvh_spectrum` / `cabin_multicam`。种子配方改成新排版；用户自建类型自己重摆。 |
| D7 | Clip 详情 | 就是展示页 `overview.detail` 按序渲染。标签树是普通原子卡 `labels_tree`，不再藏调色盘、也不再靠「有没有 nvh_spectrum」分支。 |

---

## 2. 问题

当前展示页有两套耦合：

1. **视图组件是场景包**。`nvh_spectrum` 标题就是「四通道频谱时间轴」，`ClipMediaPanel` / `ClipExplorerPage` 用 `detailIds.includes('nvh_spectrum')` 决定整页 NVH 壳（共用时间轴、NVH 文案、标签树走阵列树）。`audio_defect` 只要 overview 里放了这张卡，详情就会被当成阵列 NVH。
2. **算子口是单口**。`mel_spectrogram` / `spl_timeline` 只有 `out`。通道数是运行时 `n_channels`，展示层自己把 `boot.channels` 画成四路，编排无法给「驾驶位」单独绑一张卡。

用户要的是：编排里 N 路有名；展示页加 N 张原子卡，一张绑一口。

---

## 3. 架构

```text
operators.py          模板口 + expand_outputs_from=channel_count
recipe.graph.nodes[]  params.channel_count / port_titles
hydrate / catalog API 有效 output_ports = ch1..chN（可改 title）
kernel                仍写一份 mel/spl；口只是切片声明
overview.detail[]     原子 widget + bindings.in → {kind:upstream, step_key, port_id}
ClipExplorerPage      按 detail 顺序渲染；sync_group 相同则共享 seek
```

不改 DataWorks。本地 kernel 与现有 `capability_nvh.py` 产物布局不变。

---

## 4. 算子：通道数展开口

### 4.1 目录声明

对「一输入、按通道切出多路同型产物」的算子增加：

```json
{
  "expand_outputs_from": "channel_count",
  "output_ports": [{ "id": "out", "types": ["mel_matrix"], "title": "梅尔频谱" }]
}
```

`output_ports` 仍是 **模板**（通常一个口）。第一批启用：`mel_spectrogram`、`stft_spectrogram`、`spl_timeline`。`third_octave` 可同机制，本切片不做展示卡也可以先展开口。

舱内多路画面用 **同一展开机制**（参数名仍 `channel_count`，口 `ch1..chN` 表示流）。`encode_preview`（或写出多路 `preview_mp4` 的节点）展开后，展示页 N 张 `video_timeline` 各绑一口。本规格与种子改写一次做完，不留 `cabin_multicam`。

### 4.2 节点参数

| 字段 | 类型 | 含义 |
|------|------|------|
| `channel_count` | int，默认 1，范围 1–16 | 展开几个口 |
| `port_titles` | `{ port_id: string }` | 显示名，缺省 `ch1`… 或模板 title + 序号 |

有效口 id：**`ch1` … `chN`**（稳定、可绑定）。不要用中文做 id。

检查器：数字框改 N 时增删口；已有 `port_titles` 尽量按 id 保留；下游边若指向被删的 `chK` 则变无效（现有 DAG 黄叹号）。

### 4.3 运行时切片

| 口 | 解析 |
|----|------|
| `chK` | 通道下标 `K-1`（与 `head_meta` / `nvh` bootstrap `channels[]` 顺序一致） |
| 缺通道 | 该展示卡空态（「本路无频谱」），不让整页失败 |

kernel **不**按口各写一份 npy。展示绑定 `mel#ch2` 时，前端/bootstrap 用 `channels[1]` 的 `mel_url` / `leq_db`。

---

## 5. 原子展示组件

从 `views.py` **删除**（不可再保存）：

- `nvh_spectrum`
- `cabin_multicam`
- 整页预设 `VIEW_TEMPLATES` / `PRESET_LAYOUTS` / 编辑器 `overview_view` 下拉套版

`overview_view` 字段可留空或固定 `"custom"`，hydrate **不再**用预设填 detail。

保留并作为展示页调色盘（`surface: detail`）：

| id | 标题 | 绑定 | 渲染 |
|----|------|------|------|
| `spectrum_timeline` | 频谱时间轴 | `in` → 梅尔或 STFT 的某一个 `chK`；可选再绑同路 `spl` | 单路 ChannelSpec（谱 + 该路波形/SPL） |
| `video_timeline` | 视频时间轴 | `in` → 一路 `preview_mp4` / 抽帧流 | 单路画面 + 时间轴 |
| `asr_panel` | ASR 文本 | `in` → `asr_jsonl` | 现有 ASR 列表 |
| `labels_tree` | 标签树 | `in` → `labels_tree`（可空=用 run 上 clip labels） | `ClipLabelTreeView` |
| `json_tree` | JSON 结构 | `in` → `structured_json` / `.json` | 现有 pre |
| `frame_gallery_bbox` | 帧画廊 + BBox | 现有 needs | 暂不拆框，本切片可留 |

列表页组件（`clip_metrics` / `clip_table` / …）**不在本次展示页调色盘**；`OverviewComposer` 继续只编 `detail`。删除 `HIDDEN_PALETTE_WIDGETS` 对 `labels_tree` 的隐藏。

每张卡额外字段：

```json
{
  "key": "detail-spectrum-ch1",
  "widget_id": "spectrum_timeline",
  "bindings": { "in": { "kind": "upstream", "step_key": "mel-1", "port_id": "ch1" } },
  "sync_group": "nvh-main"
}
```

`sync_group`：空 = 独立播放头；非空字符串相同则 `ClipExplorerPage` 用同一个 `cursorNs` / seek。Composer 上是可选输入，不是再包一层容器组件。

---

## 6. Clip 详情页

`ClipExplorerPage` / `ClipMediaPanel` / `ReviewClipMediaPanel`：

- **唯一布局源** `recipe.overview.detail`（由 `clip.data_type_id` 加载配方，沿用已有 bound recipe）。
- 按数组顺序渲染。`spectrum_timeline` 不再打开「纯音频 NVH」整页壳；标签树只出现在用户放了 `labels_tree` 的位置。
- 禁止再用 `includes('nvh_spectrum')` 或「无 detail 且 wav」推断 NVH 分类树（分类树仍跟配方 `taxonomy_version_code`，与 PLAT 标签发布修复一致）。
- 校核页媒体区同样按 detail 卡渲染，避免两套壳。

---

## 7. 种子配方（打破旧卡）

| DataType | 展示页 |
|----------|--------|
| `audio_array_spec` | Mel+SPL 节点 `channel_count=4`，口名可默认 ch1–ch4；detail：四张 `spectrum_timeline` 分绑 `ch1..ch4`，同一 `sync_group`；一张 `labels_tree` |
| `audio_defect` | Mel+SPL `channel_count=1`；一张 `spectrum_timeline` 绑 `ch1`；一张 `labels_tree` |
| `oms_cabin` | 四张 `video_timeline`（按现有四路预览约定绑）+ `asr_panel` + `labels_tree`；无 `cabin_multicam` |
| `ivi_ui_stub` | `frame_gallery_bbox` + `labels_tree`（与现占位一致，去掉依赖预设 id） |

用户自建配方：打开编辑器时若仍含未知 widget，保存失败并提示「请从调色盘重摆」；不自动拆卡。

---

## 8. 编辑器 UX

1. 删「展示模板」下拉及 `onValuesChange` 里 `cardsFromPreset`。
2. 新建类型 detail 从空列表开始。
3. 梅尔/SPL/STFT 检查器：通道数、每口名称。
4. 展示卡：绑定下拉必须列出 **展开后的** `step_key/port_id`（`梅尔频谱 · 驾驶位`），不能只出现一个 `out`。
5. 同步组：卡片上可选填，placeholder「留空则独立」。

---

## 9. 错误与空态

- `channel_count` 与真实 wav 通道数不一致：多出来的卡空态；少了的口仍在，只是没有图。
- 绑定口已删除：卡上绑定控件标无效（与 DAG I/O 黄叹号同类），运行页该卡空态。
- `labels_tree` 未绑定：读当前 run 的 `fact_clip_label`（与现详情树相同）。
- 禁止为了「看起来像四通道」再暗装一张未编排的复合时间轴。

---

## 10. 测试

- **A**：`channel_count=4` hydrate 出 `ch1..ch4`；`port_titles` 改名后 catalog/保存 round-trip；未知 `nvh_spectrum` 保存 400。
- **A**：kernel 仍一份 mel；不要求四份 npy。
- **A-E2E**：`audio_array_spec` 编辑器调色盘无「四通道频谱时间轴」；展示页可加多张「频谱时间轴」并分别绑 `ch1`/`ch2`。
- **A-E2E**：`audio_defect` Clip 详情有绑定标签树、无「纯音频 NVH」；阵列 Clip 四张谱卡 + 同步组点一路齐跳（若种子设了同一 sync_group）。
- **A-E2E**：`nvh-label-tree.spec.ts` 改为断言展示页里的 `labels_tree` 卡（`overview-runtime-labels_tree` / `clip-bound-label-tree`），不再依赖「纯音频 NVH」整壳。L6 快速校核仍点树上的 `quick-review-nvh.sem.quality_grade`。

---

## 11. 明确不做

- 按通道复制 OSS 产物。
- 把 Mel / SPL / 波形拆成三个展示组件。
- 自动从 wav 推断 N（N 只来自节点参数）。
- 嵌套「同步组容器」组件。
- DataWorks / 发布 `audio_nvh-v2`。
- 回写 CURRENT 以外的里程碑抢跑（本项为用户点名的编辑器/内核改动，不是 M7.5-E2E）。
