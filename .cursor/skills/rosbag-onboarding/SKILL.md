---
name: rosbag-onboarding
description: >
  本仓库（rosbag_to_labels_pipline）新会话、项目交接、不知道从哪下手时必须先读。
  指导 Agent 读 HANDOVER/CURRENT、选对技能、遵守禁止抢跑与验收格式。
  不适用于：已经明确在改某一 API/UI 且已读过 CURRENT 的实现回合；不适用于触发 DataWorks Job；
  不适用于给无关仓库写通用 onboarding。
---

# 本仓库开工（交接 / 新会话）

Monorepo：**ROS bag 多模态平台**（SDK v1 管线 + DataType HMI + 阿里云 DataWorks）。

## Gotchas

1. **未读 CURRENT 就写业务代码** — 会做暂停项或抢跑下一里程碑。**纠正：先读 `docs/HANDOVER.md` 与 `project-management/CURRENT.md`。**
2. **把旧 Job1–4 当新 bag 主路径** — 会写入 `parsed/aligned/ai` 和 `aig_rosbag__`。**纠正：新数据走 SDK v1 + `aig_sdk__`；生产节点是 `bundled/sdk_pipeline_driver_node.py`。**
3. **publish `audio_nvh-v2` 或宣称 IVI 打标完成** — 会 archive OMS 树 / 误导产品。**纠正：CURRENT 禁止项逐条遵守。**
4. **UI 验收只写 H 不写 A-E2E** — 工单不能标 done。**纠正：可脚本化 UI 用 Playwright，见 `acceptance/_FORMAT.md`。**
5. **一次做多个工单还不回写进度** — 下一会话丢指针。**纠正：只做推荐工单；收工写四件套 + acceptance。**

<HARD-GATE>
未打开 CURRENT.md 之前，禁止改 `hmi/`、`pipeline/dataworks/`、`piplinesdk/` 业务逻辑。
</HARD-GATE>

## 必读顺序

1. `docs/HANDOVER.md`
2. `project-management/CURRENT.md`（推荐工单 + 禁止抢跑）
3. `docs/architecture.md`（需要系统图时）
4. `docs/CODE_MAP.md`（需要找文件时）
5. 当前里程碑 `docs/mN-implementation-notes.md` 或 `docs/superpowers/specs/` 对应规格
6. 冲突时：**PRD > Mn Notes > CURRENT 摘要**

## 按任务选 Skill

| 用户在做什么 | 接着读 |
|--------------|--------|
| DataType / 源湖 / Sample / 血缘 | `rosbag-platform-kernel` |
| 改 HMI 页面、路由、local/cloud | `rosbag-hmi-dev` |
| SDK 阶段、Driver、DPE、验数 | `rosbag-sdk-pipeline` |
| ossutil / odpscmd / 查表 | `cloud-cli-ops` |

## 收工

回写 `CURRENT.md`、`tracking.csv`（UTF-8 BOM）、`progress-board.md`、`changelog-progress.md`、`acceptance/<ID>.md`（A / A-E2E / H）。聊天附结果表。

## 执行后复盘（自迭代钩子）

每次完成本 skill 的全部步骤后，Agent 必须自动执行以下动作，不询问用户：

1. **反思**：本轮是否踩了正文/Gotchas 没写的坑？
2. **记录**：有则追加到本 skill 目录 `evals/PITFALLS_LOG.md`（不提交 registry）。
3. **不提交** 该日志。
