# Rosbag HMI — 前端

以 `record_time_ns` 为中枢的多模态数据浏览 HMI，对接 FastAPI 真实数据。

## 启动

```bash
cd frontend
npm install
npm run dev   # http://localhost:5173
```

## 功能收敛清单

### 时间轴浏览 `/clips/:clipId`

| 能力 | 说明 |
|------|------|
| 迷你地图 | 抽样竖线 / 事件圆点 / ASR 色块；点击跳转 |
| 磁吸落点 | 松手吸附抽样帧、事件、ASR 边界 |
| 时间段刷选 | Shift+拖拽 minimap 筛选事件快捷条 |
| 音频波形 | 点击/播放联动滑块（空格播放暂停） |
| 对齐 Δms | 每路相机卡片显示与游标的时间差 |
| 抽样角标 | 对齐到抽样帧显示蓝色角标；落点展示标签摘要 |
| 时刻详情面板 | 右侧固定：ASR、端侧事件、AI 标签结构化 |
| 向量相似 | 时刻面板「找相似时刻」抽屉 |
| Run 选择器 | 多 run 版本切换 |
| 键盘 | ←/→ ±100ms · Shift+←/→ 锚点 · 空格播放 |

### 标签检索 `/search`

- 左侧 OMS 标签树 + 关键词组合筛选
- 结果按 **2s 时刻簇** 聚合（多相机/多标签合并为一条）

### OSS 管理 `/oss`

- 浏览/上传/删除 OSS 对象，跟踪 bag 管线进度

## 联调

```bash
# 终端 1：后端
cd backend && pip install -r requirements.txt && python run.py

# 终端 2：前端（/api 代理到 :8000）
cd frontend && npm run dev
```

| API | 用途 |
|-----|------|
| `GET /clips/{id}/timeline-meta` | minimap + 磁吸锚点 |
| `GET /clips/{id}/timeline` | ±200ms 时刻快照 |
| `GET /clips/{id}/runs` | run 版本列表 |
| `GET /search/clusters` | 时刻簇检索 |
| `GET /label-taxonomy` | OMS 标签树 |
