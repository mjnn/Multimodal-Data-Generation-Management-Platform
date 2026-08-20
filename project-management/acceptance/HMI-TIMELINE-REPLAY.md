# HMI-TIMELINE-REPLAY · Clip 时间轴重播 · 验收清单

> 格式：`project-management/acceptance/_FORMAT.md`

| 字段 | 内容 |
|------|------|
| 工单 | HMI-TIMELINE-REPLAY · Clip / NVH 时间轴重播 |
| 日期 | 2026-08-20 |
| 环境前置 | 否（A-1 纯前端断言；H 需本地 HMI） |
| Agent 自动化摘要 | playback 断言通过；舱内 `AudioWaveform` + NVH `AudioNvhTimelinePanel` 均有「重播」与结束再播从头 |

---

## 一、Agent / 自动化

### A · 单元 / API / 构建

#### A-1 · playback 工具函数断言

**操作步骤**
1. `cd hmi/frontend`
2. `node --experimental-strip-types scripts/playback.assert.mts`

**期望结果**
- 打印 `playback.assert.mts: ok`

**通过判断标准**
- exit 0

**执行记录**
- 2026-08-20：`playback.assert.mts: ok`（exit 0）

---

### A-E2E · Playwright / Selenium

本工单无独立 Playwright（需真实 clip 媒体；逻辑已用 A-1 覆盖）。UI 断言路径：

- Cabin：`data-testid="clip-timeline-replay"` / `clip-timeline-play`
- NVH：`data-testid="audio-nvh-replay"` / `audio-nvh-play`

---

## 二、人工签字 / 主观（H · 可选）

#### H-1 · 舱内 / NVH 手动重播

**操作步骤**
1. Explorer 打开有 MP4 的舱内 clip：播到结尾 → 点「重播」或再点「播放」/空格 → 应从开头播放
2. 打开 audio_array_spec NVH clip：同上

**期望结果**
- 结束态再播从头；「重播」随时可从头；空格仍为播放/暂停

**执行记录**
- （待人点）

---

## 三、不在本工单范围

- PLAT-AUDIO-AI-LABEL / nvh_deriver / recipe
- UI-NVH-REVIEW-SAVE

---

## 四、点测结论

- [x] A-1 通过
- [ ] H-1 待人
- 可标 done（A 绿；H 可选）
