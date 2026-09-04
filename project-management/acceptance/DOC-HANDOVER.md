# DOC-HANDOVER · 项目交接文档与技能包 · 验收清单

> 格式：`project-management/acceptance/_FORMAT.md`

| 字段 | 内容 |
|------|------|
| 工单 | DOC-HANDOVER · 交接 Wiki / 架构图 / Agent 技能包 / 压缩脚本 |
| 日期 | 2026-08-25 |
| 环境前置 | 无 UI 行为改动；不要求双端常驻 |
| Agent 自动化摘要 | 文档与技能包落地；pack 脚本已生成 zip |

---

## 一、Agent / 自动化

### A · 单元 / API / 构建

#### A-1 · 交接入口文件存在且可互相跳转

**操作步骤**
1. 确认 `docs/HANDOVER.md`、`docs/architecture.md`、`docs/CODE_MAP.md` 存在
2. 确认 `docs/WIKI.md` 文首指向上述三文件
3. 确认 `.cursor/skills/rosbag-onboarding/SKILL.md` 等四个新 skill 存在
4. 确认 `handover/pack_handover.py` 可运行

**期望结果**
- 新同事/Agent 能从 HANDOVER 找到 CURRENT、架构图、技能表
- 技能 name 与目录名一致

**通过判断标准**
- 路径均存在；HANDOVER 含禁止抢跑与推荐工单指针

**执行记录**
- 2026-08-25 Agent：文件已写入；Wiki 文首与 README 已加链接

#### A-2 · 生成交接压缩包

**操作步骤**
1. `py -3 handover/pack_handover.py`

**期望结果**
- `handover-output/rosbag-labels-handover-*.zip` **一份**完整包（源码 + 文档 + skills + rules）
- 包内不含 `.env`、不含 `node_modules`、不含 `hmi_runtime`

**通过判断标准**
- 脚本 exit 0；单个 zip 非空；顶层目录 `rosbag_to_labels_pipline/`

**执行记录**
- 2026-08-26 Agent：单包 `handover-output/rosbag-labels-handover-2026-08-26.zip` **56.0 MB / 924 files**；顶层 `rosbag_to_labels_pipline/`；含 docs、skills、rules、样例 bag；无 `.env`

### A-E2E · Playwright / Selenium

本工单无 UI 行为改动，无 A-E2E。

---

## 二、人工签字 / 主观（H · 可选）

无。文档交接不需要主观签字。

---

## 三、不在本工单范围

- UI-NVH-REVIEW-SAVE
- publish `audio_nvh-v2`
- 修改 DataWorks 节点业务逻辑
- 给全仓库每一行加注释（以模块头 + CODE_MAP 代替）

---

## 四、点测结论

- [x] A — 可标 done（A-2 以 pack 脚本输出为准）
- [x] 无 A-E2E / 无 H
