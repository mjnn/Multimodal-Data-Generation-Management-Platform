# FIX-SPA-PREFIX · 直连 :8012 子路径空白页 · 验收清单

> 格式：`project-management/acceptance/_FORMAT.md`

| 字段 | 内容 |
|------|------|
| 工单 | FIX-SPA-PREFIX · 剥 `/tools/rosbag-labels` 前缀以加载 assets |
| 日期 | 2026-08-28 |
| 环境前置 | 否（pytest/脚本） |
| Agent 自动化摘要 | `test_public_ui_prefix.py` 前缀解析 + HTTP assets/health 通过 |

---

## 一、Agent / 自动化

### A · 单元 / API / 构建

#### A-1 · 带前缀的 JS 返回脚本而非 HTML

**操作步骤**
1. `cd hmi/backend`
2. `py -3 scripts/test_public_ui_prefix.py`

**期望结果**
- prefix parse / strip scope OK
- `GET /tools/rosbag-labels/assets/index-dWQdwbLO.js` 含 JS
- `GET /tools/rosbag-labels/api/health` JSON `ok: true`

**通过判断标准**
- 脚本 exit 0

**执行记录**
- 2026-08-28 Agent：`OK HTTP prefixed assets + health`

### A-E2E

无浏览器改动文件；POC 需 **重新 docker save/load** 后人工打开页面。本工单不写 H。

---

## 二、不在本工单范围

- 在 POC 上代为发版
- UI-NVH-REVIEW-SAVE

---

## 三、点测结论

- [x] A-1 可标 done
