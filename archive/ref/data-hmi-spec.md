# Data HMI 项目规格说明书

> 版本：1.0 | 日期：2026-05-19

---

## 1. 项目概述

### 1.1 项目名称

Data HMI — 数据打标流程人机交互系统

### 1.2 项目目标

为上汽（shangqi）数据管线提供可视化管理界面，支持对音频/视频采集数据的：

- 打标流程状态监控（转录 → 打标 → 向量化）
- 数据内容浏览与检索
- 基于标签的模糊搜索
- 基于 embedding 的向量相似检索

### 1.3 目标用户

数据工程团队内部使用，用于监控和排查数据管线的处理进度与质量。

---

## 2. 系统架构

### 2.1 整体架构

```
┌──────────────────┐    HTTP/REST     ┌──────────────────┐    ODPS SDK     ┌──────────────┐
│   前端 (React)   │  ←─────────────→ │  后端 (FastAPI)  │  ←────────────→ │  ODPS 表     │
│  localhost:5173  │                   │  localhost:8000  │                 │  (MaxCompute) │
└──────────────────┘                   └────────┬─────────┘                 └──────────────┘
                                              │
                                              │ oss2 SDK (签名)
                                              ▼
                                       ┌──────────────┐
                                       │   阿里云 OSS  │
                                       │  (对象存储)   │
                                       └──────────────┘
```

### 2.2 技术选型

| 层级 | 技术 | 版本 | 说明 |
|------|------|------|------|
| 前端框架 | React + TypeScript | React 19, TS 6 | SPA 单页应用 |
| UI 组件库 | Ant Design | 6.x | 中后台组件 |
| 路由 | React Router DOM | 7.x | 客户端路由 |
| HTTP 客户端 | Axios | 1.x | API 请求 |
| 构建工具 | Vite | 8.x | 开发服务器 + 构建 |
| 后端框架 | FastAPI + Uvicorn | 0.115+ | 异步 ASGI |
| 数据库访问 | PyODPS | 0.12+ | 阿里云 MaxCompute SDK |
| 对象存储 | oss2 | 2.18+ | OSS 预签名 |
| 向量计算 | NumPy | 1.26+ | 内存级余弦相似度 |
| 配置管理 | python-dotenv | 1.0+ | .env 文件 |

### 2.3 前后端通信

- 开发环境：Vite dev server 将 `/api` 反向代理到 `http://127.0.0.1:8000`
- 生产环境：通过 `VITE_API_BASE_URL` 环境变量配置 API 地址
- 请求超时：90 秒（ODPS SQL 执行耗时不固定）

---

## 3. 数据模型

### 3.1 ODPS 核心表

系统依赖 MaxCompute 项目中的三张表：

#### 3.1.1 `shangqi_audio_labels` — 音频打标结果

| 字段 | 类型 | 说明 |
|------|------|------|
| `audio_path` | STRING | 音频 OSS 路径（主键，格式 `oss://endpoint/bucket/key`） |
| `transcript` | STRING | 语音转写文本 |
| `label_text` | STRING | LLM 生成的标签（长 markdown） |
| `label_embedding` | STRING | 标签文本向量（JSON 数组字符串） |
| `status` | STRING | 处理状态 |
| `error_stage` | STRING | 错误阶段 |
| `error_msg` | STRING | 错误信息 |

#### 3.1.2 `shangqi_video_frames` — 视频抽帧记录

| 字段 | 类型 | 说明 |
|------|------|------|
| `video_path` | STRING | 视频 OSS 路径（联合主键） |
| `frame_idx` | BIGINT | 帧序号（联合主键，从 0 开始） |
| `frame_path` | STRING | 帧图片 OSS 路径 |
| `status` | STRING | 抽帧处理状态 |
| `error_stage` | STRING | 错误阶段 |
| `error_msg` | STRING | 错误信息 |

#### 3.1.3 `shangqi_video_labels` — 视频帧打标结果

| 字段 | 类型 | 说明 |
|------|------|------|
| `video_path` | STRING | 视频 OSS 路径（联合主键） |
| `frame_idx` | BIGINT | 帧序号（联合主键） |
| `frame_path` | STRING | 帧图片 OSS 路径 |
| `label_text` | STRING | LLM 生成的标签（长 markdown） |
| `label_embedding` | STRING | 标签文本向量（JSON 数组字符串） |
| `image_embedding` | STRING | 图像向量（JSON 数组字符串） |
| `label_input_token` | BIGINT | 打标输入 token 数 |
| `label_output_token` | BIGINT | 打标输出 token 数 |
| `label_embedding_total_token` | BIGINT | 标签向量化总 token 数 |
| `image_embedding_total_token` | BIGINT | 图像向量化总 token 数 |
| `status` | STRING | 处理状态 |
| `error_stage` | STRING | 错误阶段 |
| `error_msg` | STRING | 错误信息 |

### 3.2 表关联

```
shangqi_video_frames (1) ──< shangqi_video_labels (0..1)
  JOIN ON: video_path = video_path AND frame_idx = frame_idx

shangqi_audio_labels — 独立表，无 JOIN
```

### 3.3 Composite ID 编码

系统使用 `|` 分隔符构造全局唯一标识符，替代自增主键：

| 数据类型 | 格式 | 示例 |
|----------|------|------|
| Audio | `a\|{audio_path}` | `a\|oss://bucket/cabin/0001.mp3` |
| Video Frame | `v\|{video_path}\|{frame_idx}` | `v\|oss://bucket/scene_a/001.mp4\|42` |

设计依据：`|` 字符不会出现在 OSS 路径中，作为分隔符是安全的。前后端共享此编解码规则。

### 3.4 Status 归一化映射

ODPS 表中 status 字段存在多种原始值，后端统一映射为前端 5 种枚举：

| 归一化值 | 原始值集合 | 含义 |
|----------|-----------|------|
| `success` | ok, success, succeeded, done | 处理完成 |
| `failed` | failed, error, fail | 处理失败 |
| `running` | running, processing, in_progress | 执行中 |
| `pending` | pending, waiting, queued, 空值, 其他 | 待执行 |
| `skipped` | skipped, skip | 已跳过 |

---

## 4. API 接口规格

Base path: `/api`

### 4.1 健康检查

#### `GET /api/health`

**Response:**

```json
{
  "ok": true,
  "project": "maxframe_oss"
}
```

### 4.2 缓存管理

#### `POST /api/cache-clear`

清除后端 SQL 查询缓存。

**Response:**

```json
{
  "cleared": 5
}
```

### 4.3 数据总览

#### `GET /api/overview`

聚合查询 audio_path 和 video_path 列表。

**Query Params:**

| 参数 | 类型 | 默认 | 约束 | 说明 |
|------|------|------|------|------|
| `page` | int | 1 | >= 1 | 页码 |
| `page_size` | int | 20 | 1-200 | 每页条数 |
| `kind` | string | null | audio / video | 过滤数据类型 |
| `status` | string | null | 5 种枚举 | 过滤状态 |
| `keyword` | string | null | - | 按 source_path 模糊搜索 |

**Response:**

```json
{
  "total": 30,
  "page": 1,
  "page_size": 20,
  "items": [
    {
      "kind": "video",
      "source_path": "oss://maxframe-bucket/shangqi/video/scene_a/001.mp4",
      "status": "success",
      "error_count": 0,
      "frame_count": 30,
      "labeled_count": 25,
      "embedded_count": 20
    },
    {
      "kind": "audio",
      "source_path": "oss://maxframe-bucket/shangqi/audio/cabin/0001.mp3",
      "status": "success",
      "error_count": 0,
      "transcript_preview": "小度小度，导航回家",
      "label_preview": "导航指令，前方右转",
      "has_embedding": true
    }
  ]
}
```

### 4.4 视频概览

#### `GET /api/video-overview`

查询单个视频的统计信息。

**Query Params:**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `video_path` | string | 是 | 视频 OSS 路径 |

**Response:**

```json
{
  "video_path": "oss://...",
  "total_frames": 30,
  "labeled_frames": 25,
  "embedded_frames": 20,
  "error_frames": 1,
  "top_labels": [
    { "label": "高速公路场景，多车道...", "count": 12 },
    { "label": "城市道路，红绿灯...", "count": 8 }
  ]
}
```

### 4.5 视频帧列表

#### `GET /api/video-frames`

分页查询某视频的抽帧列表。

**Query Params:**

| 参数 | 类型 | 默认 | 约束 | 说明 |
|------|------|------|------|------|
| `video_path` | string | - | 必填 | 视频 OSS 路径 |
| `page` | int | 1 | >= 1 | 页码 |
| `page_size` | int | 30 | 1-200 | 每页条数 |

**Response:**

```json
{
  "total": 30,
  "page": 1,
  "page_size": 30,
  "items": [
    {
      "composite_id": "v|oss://.../001.mp4|0",
      "video_path": "oss://.../001.mp4",
      "frame_idx": 0,
      "frame_path": "https://signed-url...",
      "status": "success",
      "has_label": true,
      "label_text": "高速公路场景..."
    }
  ]
}
```

> `frame_path` 已从 `oss://` 转换为预签名 HTTPS URL。

### 4.6 帧/音频详情

#### `GET /api/frame-detail`

通过 composite id 查询单帧或单条音频的完整信息。

**Query Params:**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | string | 是 | Composite ID（`a\|...` 或 `v\|...\|N`） |

**Audio Response:**

```json
{
  "kind": "audio",
  "composite_id": "a|oss://...",
  "audio_path": "oss://...",
  "audio_url": "https://signed-url...",
  "transcript": "小度小度，导航回家",
  "label_text": "导航指令，前方右转...",
  "label_embedding_dim": 1024,
  "status": "success",
  "error_stage": null,
  "error_msg": null
}
```

**Video Response:**

```json
{
  "kind": "video",
  "composite_id": "v|oss://...|0",
  "video_path": "oss://...",
  "frame_idx": 0,
  "frame_path": "https://signed-url...",
  "label_text": "高速公路场景...",
  "label_embedding_dim": 1024,
  "image_embedding_dim": 768,
  "tokens": {
    "label_input": 850,
    "label_output": 120,
    "label_embedding": 110,
    "image_embedding": 1024
  },
  "status": "success",
  "error_stage": null,
  "error_msg": null
}
```

### 4.7 标签搜索建议

#### `GET /api/label-suggestions`

返回一组常见搜索关键词。

**Response:**

```json
["驾驶", "睡觉", "儿童", "风险", "无", "导航", "标签", "场景", "MPV", "SUV", "后排", "广角", "ok", "未驾驶"]
```

### 4.8 标签搜索

#### `GET /api/search`

按标签文本模糊匹配（LIKE），跨 audio + video 表搜索。

**Query Params:**

| 参数 | 类型 | 默认 | 约束 | 说明 |
|------|------|------|------|------|
| `keyword` | string | - | 必填 | 搜索关键词 |
| `page` | int | 1 | >= 1 | 页码 |
| `page_size` | int | 20 | 1-200 | 每页条数 |

**Response:**

```json
{
  "total": 15,
  "page": 1,
  "page_size": 20,
  "items": [
    {
      "composite_id": "v|oss://...|5",
      "kind": "video",
      "source_path": "oss://...",
      "preview_url": "https://signed-url...",
      "label_text": "高速公路场景...",
      "has_label_embedding": true,
      "has_image_embedding": true,
      "status": "success"
    }
  ]
}
```

### 4.9 向量相似检索

#### `GET /api/similar`

基于 embedding 的余弦相似度 Top-K 检索。

**Query Params:**

| 参数 | 类型 | 默认 | 约束 | 说明 |
|------|------|------|------|------|
| `id` | string | - | 必填 | 查询项的 Composite ID |
| `top_k` | int | 360 | 1–500 | 返回数量上限（由 `SIMILAR_MAX_TOP_K` 配置，默认 500） |
| `min_score` | float | 0.8 | 0.0–1.0 | 最低余弦相似度阈值 |

**行为说明：**

- Video：使用 `image_embedding` 字段计算相似度（全局 corpus，非单视频内）
- Audio：使用 `label_embedding` 字段计算相似度
- 排除自身
- 仅匹配同维度向量的候选项
- 结果按相似度降序，且 `score >= min_score`

**Response:**

```json
{
  "scope": "global",
  "candidate_count": 120,
  "max_top_k": 120,
  "min_score": 0.8,
  "items": [
    {
      "composite_id": "v|oss://...|3",
      "kind": "video",
      "source_path": "oss://...",
      "frame_idx": 3,
      "video_label": "oms/001",
      "preview_url": "/api/media/...",
      "score": 0.9521
    }
  ]
}
```

### 4.10 错误响应

| 状态码 | 触发场景 |
|--------|----------|
| 400 | Composite ID 格式错误 |
| 404 | 资源不存在 / 无 embedding |
| 500 | ODPS 执行异常 |

---

## 5. 前端页面规格

### 5.1 全局布局

```
┌─────────┬──────────────────────────────────┐
│ Data HMI│  数据打标流程 HMI                 │
│─────────│──────────────────────────────────│
│ 数据总览 │                                  │
│ 标签搜索 │        <Outlet /> 内容区          │
│ 向量检索 │                                  │
│         │                                  │
└─────────┴──────────────────────────────────┘
  Sider(200px, dark)    Header + Content
```

### 5.2 页面一：数据总览 `/`

**功能：**

- 顶部统计卡片：数据总量、视频数、音频数、错误项总数
- 筛选栏：数据类型（audio/video）、状态（5 种）、路径关键词搜索
- 数据表格：分页展示 overview 聚合结果

**表格列定义：**

| 列 | 字段 | 宽度 | 说明 |
|---|---|---|---|
| 类型 | kind | 100 | Tag 展示，video=蓝色，audio=品红 |
| 路径 | source_path | 自适应 | monospace 字体，ellipses |
| 状态 | status | 110 | PipelineStatus 组件 |
| 内容/进度 | — | 280 | Video: 帧数/已打标/embed + Progress; Audio: 转录预览 + 标签预览 + embed 标记 |
| 错误 | error_count | 70 | >0 红色 Tag |
| 操作 | — | 110 | Video→查看抽帧; Audio→查看详情 |

**交互：**

- 点击视频行 → `/raw-data/{video_path}`
- 点击音频行 → `/frames/{a|audio_path}`

### 5.3 页面二：视频抽帧网格 `/raw-data/:id`

**功能：**

- 视频路径信息卡片
- 统计卡片行：总帧数、已打标（含百分比）、已 embed（含百分比）、错误帧
- 高频标签展示（Top-5 label_text + 出现次数）
- 帧缩略图网格（auto-fill, minmax(200px, 1fr)），每帧卡片展示：
  - 帧图片
  - 帧序号 + 状态 Tag
  - 标签预览或"未标注"
- 底部分页器（每页 30 帧）

**交互：**

- 点击帧卡片 → `/frames/{composite_id}`

### 5.4 页面三：帧/音频详情 `/frames/:id`

**布局：** 左右分栏（14:10）

#### 音频详情

| 左侧 (14) | 右侧 (10) |
|---|---|
| 音频播放器 + 路径信息 | Tab: 标签 / 向量 / 状态 |
| 转录文本卡片 | |

#### 视频帧详情

| 左侧 (14) | 右侧 (10) |
|---|---|
| 帧图片 + 路径/帧序号信息 | Tab: 标签 / 向量 / Tokens / 状态 |

**各 Tab 内容：**

| Tab | Audio | Video |
|-----|-------|-------|
| 标签 | label_text 原文（pre-wrap） | label_text 原文（pre-wrap） |
| 向量 | label_embedding 维度 | label_embedding + image_embedding 维度 |
| Tokens | — | 4 项 token 统计数值 |
| 状态 | PipelineStatus + error_stage + error_msg | PipelineStatus + error_stage + error_msg |

**交互：**

- "找相似"按钮 → `/vector-search?id={composite_id}`

### 5.5 页面四：标签搜索 `/search`

**功能：**

- AutoComplete 搜索栏（带建议词下拉）
- 搜索结果卡片网格（auto-fill, minmax(360px, 1fr)），每张卡片：
  - 左侧：帧缩略图或音频图标占位
  - 右侧：类型 Tag + 状态 + 标签文本（2 行截断）+ 路径 + embedding 标记
- 分页器
- 未搜索时显示快捷搜索按钮

### 5.6 页面五：向量检索 `/vector-search`

**功能：**

- 输入栏：Composite ID 输入框 + Top-K 数字输入 + 检索按钮
- 信息提示：embedding 计算方式说明
- 结果展示：响应式网格（xs=12, sm=8, md=6, lg=4），每张卡片：
  - 帧图片或音频图标
  - 相似度分数（>0.9 绿色，>0.7 橙色，其他红色）
  - 排名序号
  - 数据类型 Tag
  - 源路径

**交互：**

- 支持 URL 参数 `?id=...` 自动填充并触发检索（从 FrameDetail 跳转）
- 点击结果卡片 → `/frames/{composite_id}`

---

## 6. 公共组件

### 6.1 PipelineStatus

**位置：** `src/components/PipelineStatus.tsx`

**功能：** 管线状态展示组件，渲染为 Ant Design Tag + 图标。

| 状态 | 颜色 | 图标 | 文本 |
|------|------|------|------|
| success | green | CheckCircleOutlined | 成功 |
| failed | red | CloseCircleOutlined | 失败 |
| running | blue | SyncOutlined (spin) | 执行中 |
| pending | orange | ClockCircleOutlined | 待执行 |
| skipped | default | MinusCircleOutlined | 跳过 |

**Props:**

| 属性 | 类型 | 必填 | 说明 |
|------|------|------|------|
| status | PipelineStatus | 是 | 状态枚举值 |
| errorStage | string | 否 | 错误阶段（failed 时 Tooltip 展示） |
| errorMsg | string | 否 | 错误信息（failed 时 Tooltip 展示） |
| size | 'small' \| 'default' | 否 | Tag 尺寸 |

---

## 7. 后端模块规格

### 7.1 `app.py` — 主服务

**职责：** FastAPI 应用入口，包含所有 API 端点定义和业务逻辑。

**关键机制：**

| 机制 | 说明 |
|------|------|
| 启动预热 | `_warmup()` 在后台线程预跑 overview + video_overview + video_frames，填充缓存 |
| CORS | 允许 `localhost:5173` 和 `127.0.0.1:5173` |
| OSS 签名 | 出参中所有 `oss://` 路径自动替换为预签名 HTTPS URL |
| Label 截断 | `_label_summary()` 将长 markdown 标签截断为 80 字符单行预览 |

### 7.2 `db.py` — 数据库层

**职责：** ODPS 连接管理和 SQL 执行。

| 函数 | 说明 |
|------|------|
| `odps()` | 懒加载 ODPS 连接实例（lru_cache） |
| `query(sql, cache=True)` | 执行 SQL 返回 list[dict]，默认 5 分钟 TTL 缓存 |
| `query_iter(sql)` | 流式迭代器，省内存 |
| `sql_quote(s)` | SQL 字符串转义，防注入 |
| `normalize_status(raw)` | Status 归一化映射 |
| `cache_clear()` | 清除查询缓存 |

**缓存配置：** `TTLCache(maxsize=256, ttl=300)` — 最多 256 条 SQL，5 分钟过期。

### 7.3 `oss_signer.py` — OSS 签名

**职责：** 将 `oss://` 路径转换为浏览器可访问的预签名 HTTPS URL。

| 函数 | 说明 |
|------|------|
| `parse_oss_url(url)` | 解析 `oss://endpoint/bucket/key` 为 (bucket, key) |
| `sign_url(oss_url, expires=3600)` | 生成预签名 URL，1 小时有效 |

**关键设计：** 签名时始终使用 `.env` 中配置的外网 endpoint（`OSS_ENDPOINT`），因为浏览器在用户机器上无法访问内网 endpoint。

### 7.4 `vec.py` — 向量计算

**职责：** 从 ODPS string 字段解析 embedding 并计算余弦相似度。

| 函数 | 说明 |
|------|------|
| `parse_embedding(s)` | JSON 字符串 → numpy float32 数组 |
| `cos_sim(a, b)` | 余弦相似度 |
| `similar_filtered(query_vec, candidates, min_score, top_k)` | 阈值过滤 + Top-K 相似项排序 |

**限制：** 内存级实现，将所有候选 embedding 加载到内存计算，仅适合 demo 数据规模。

### 7.5 `probe.py` — 探针脚本

**职责：** 独立运行脚本，验证 ODPS 连通性和三表数据格式，检查 `*_path` 字段是否为 `oss://` 格式，抽样 `embedding` 字段长度。

---

## 8. 环境配置

### 8.1 后端环境变量

| 变量 | 必填 | 说明 | 示例 |
|------|------|------|------|
| `ODPS_ACCESS_ID` | 是 | MaxCompute AccessKey ID | — |
| `ODPS_SECRET_ACCESS_KEY` | 是 | MaxCompute AccessKey Secret | — |
| `ODPS_PROJECT` | 是 | ODPS 项目名 | `maxframe_oss` |
| `ODPS_ENDPOINT` | 是 | ODPS 服务 endpoint | `http://...` |
| `OSS_ACCESS_ID` | 是 | OSS AccessKey ID | — |
| `OSS_SECRET_ACCESS_KEY` | 是 | OSS AccessKey Secret | — |
| `OSS_ENDPOINT` | 是 | OSS 外网 endpoint | `https://oss-cn-hangzhou.aliyuncs.com` |
| `PORT` | 否 | 服务端口 | `8000`（默认） |

### 8.2 前端环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `VITE_API_BASE_URL` | API 基础路径 | `/api` |

### 8.3 Vite 代理配置

```typescript
server: {
  proxy: {
    '/api': {
      target: 'http://127.0.0.1:8000',
      changeOrigin: true,
    },
  },
}
```

---

## 9. Mock 数据规格

### 9.1 开关

`src/api/index.ts` 中 `USE_MOCK = false`，切换为 `true` 即可使用 mock 数据。

### 9.2 Mock 数据集

| 数据 | 规模 | 说明 |
|------|------|------|
| VIDEO_PATHS | 12 个视频 | 4 种场景 (scene_a/b/c/d)，各 3 段 |
| AUDIO_PATHS | 18 条音频 | 3 种类型 (cabin/navi/wakeup)，各 6 条 |
| FRAMES_PER_VIDEO | 30 帧/视频 | — |
| 图片占位 | picsum.photos | 使用 seed 确定性生成 |
| 状态分布 | success:failed:running:pending ≈ 4:1:1:1 | — |

### 9.3 伪随机策略

使用确定性伪随机函数 `rand(seed) = frac(sin(seed) * 10000)`，保证相同 seed 总是返回相同数据。

---

## 10. 设计决策记录

### 10.1 ODPS 替代 Hologres

| 维度 | 原设计 (Hologres) | 实际实现 (ODPS) |
|------|-------------------|-----------------|
| 驱动 | psycopg2 (PostgreSQL) | pyodps |
| 表结构 | 6 表规范化 | 3 表扁平化 |
| 向量检索 | Proxima 引擎 (SQL) | NumPy 内存计算 |
| 实时性 | TCP 直连，毫秒级 | ODPS instance 提交，秒级 |
| 原因 | — | 数据已存在于 MaxCompute，无需迁移 |

### 10.2 Composite ID 替代自增主键

ODPS 表无自增主键，且跨表关联需唯一标识。设计 `a|...` / `v|...|N` 编码方案，前后端共享编解码，URL 路径参数可直接传递。

### 10.3 SQL 缓存

ODPS 每次 SQL 提交有秒级 instance 开销，数据基本静态（已完成的打标结果），5 分钟 TTL 缓存是合理的性能-实时性折中。

### 10.4 向量检索内存级实现

当前数据规模小，全量加载 embedding 到内存计算余弦相似度可接受。若数据量增长，需迁移至专业向量数据库（如 Hologres Proxima / Milvus）。

---

## 11. 启动与部署

### 11.1 开发环境启动

```bash
# 后端
cd hmi/backend
cp .env.example .env          # 填入真实 AK/SK
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --reload --port 8000

# 前端
cd frontend
npm install
npm run dev                   # http://localhost:5173
```

### 11.2 生产构建

```bash
cd frontend
npm run build                 # 输出到 dist/
```

### 11.3 连通性验证

```bash
cd hmi/backend
source .venv/bin/activate
python probe.py               # 检查 ODPS 连通性和三表数据
```

---

## 12. 已知限制与待改进项

| 项目 | 当前状态 | 改进方向 |
|------|----------|----------|
| 向量检索 | NumPy 内存级，全量加载 | 迁移到向量数据库支持 ANN |
| 缓存 | 静态 TTL，无主动失效 | 数据更新时触发缓存清除 |
| 前端状态管理 | 各页面 useState 局部管理 | 可引入 Zustand 全局缓存 |
| SQL 拼接 | f-string + sql_quote | 可引入参数化查询更安全 |
| 错误处理 | 部分端点缺少统一错误格式 | 统一 ErrorResponse model |
| 分页 | 部分端点先全量再切片 | 改为数据库侧分页 |
| Mock 数据 | 与真实数据结构可能有偏差 | 对齐 ODPS 实际数据抽样 |
| Zustand | 已声明依赖但未使用 | 评估是否需要或移除依赖 |
