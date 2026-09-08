# FIX-ENCODE-FFMPEG · 视频编码器找不到 ffmpeg · 验收清单

> 格式：`project-management/acceptance/_FORMAT.md`

| 字段 | 内容 |
|------|------|
| 工单 | FIX-ENCODE-FFMPEG · Windows 无 PATH ffmpeg 时 encode_preview 用 imageio-ffmpeg 捆绑二进制 |
| 日期 | 2026-09-04 |
| 环境前置 | 否（unittest + 本地 encode smoke） |
| Agent 自动化摘要 | `test_clip_video_ffmpeg` 3/3；bbox 15/15；resolve 落到捆绑 `ffmpeg-win-x86_64-v7.1.exe` 并写出 MP4 |

---

## 一、Agent / 自动化

### A · 单元 / API / 构建

#### A-1 · get_ffmpeg_exe 抛错仍落到捆绑二进制

**操作步骤**
1. `cd piplinesdk`
2. `py -3 -m unittest discover -s tests -p "test_clip_video_ffmpeg.py" -v`

**期望结果**
- PATH 无 ffmpeg 且 `get_ffmpeg_exe()` 抛 `No ffmpeg exe could be found...` 时，`resolve_ffmpeg()` 仍返回 `imageio_ffmpeg/binaries/ffmpeg*`
- `IMAGEIO_FFMPEG_EXE` 指向存在的文件时优先用该路径
- 全无可用二进制时抛本仓库文案，不再原样抛 imageio 那句

**通过判断标准**
- 3 tests OK

**执行记录**
- 2026-09-04 Agent：`Ran 3 tests ... OK`

#### A-2 · 真实编码 smoke（本机无系统 ffmpeg）

**操作步骤**
1. `cd piplinesdk`
2. 调用 `resolve_ffmpeg()` + `encode_clip_mp4` 写一帧 JPEG + 空 WAV

**期望结果**
- `resolve_ffmpeg()` 返回 site-packages 内 `ffmpeg-win-x86_64-v7.1.exe`
- 产出 `clip_preview.mp4` 且文件存在

**通过判断标准**
- 未出现 `No ffmpeg exe could be found`

**执行记录**
- 2026-09-04 Agent：`resolve ...\ffmpeg-win-x86_64-v7.1.exe`；`encoded ... clip_preview.mp4 size 261`；`encode smoke ok`
- 回归：`test_bbox_capability` 15/15 OK

### A-E2E · Playwright / Selenium

本工单无 UI 改动，无 A-E2E。

---

## 二、人工签字 / 主观（H · 可选）

#### H-1 · 重跑失败的 oms_cabin 任务

在管线管理对失败 clip 再开跑，视频编码器应变为成功（本机 PATH 仍无 `ffmpeg` 亦可）。

---

## 三、不在本工单范围

- 安装系统级 ffmpeg
- DataWorks / DPE 镜像（镜像已 apt 装 ffmpeg）
- UI-NVH-REVIEW-SAVE

---

## 四、点测结论

- [x] A 全绿；无 A-E2E；H-1 待用户重跑任务
