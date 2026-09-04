# DOC-INTRANET-CICD · 域内部署与 docker save/load/run · 验收清单

> 格式：`project-management/acceptance/_FORMAT.md`

| 字段 | 内容 |
|------|------|
| 工单 | DOC-INTRANET-CICD · 交接：堡垒机 + Dockerfile + save/load/run |
| 日期 | 2026-08-27 |
| 环境前置 | 文档工单；不在 POC 上真实 load（无堡垒机密钥入库） |
| Agent 自动化摘要 | 文档与 `save-image.ps1` 已落盘；口令未写入仓库 |

---

## 一、Agent / 自动化

### A · 单元 / API / 构建

#### A-1 · 文档覆盖指南要求的三块

**操作步骤**
1. 打开 `docs/deploy-intranet-cicd.md`
2. 确认含：开发机项目目录 `docker save`、Dockerfile 说明、堡垒机登录后 `docker load` 与 `docker run` 参数表
3. 确认 `hmi/deploy/save-image.ps1` 存在且注释要求仓库根
4. 确认文中**没有**堡垒机明文密码

**期望结果**
- 接手人能按文档在仓库根 save、SFTP、POC 上 load/run
- 密钥仍只在原 Word / CI

**通过判断标准**
- 上述文件存在；HANDOVER / README 已链接；检索仓库无 Word 中的口令串

**执行记录**
- 2026-08-27 Agent：文档与脚本已写；提取用的临时 txt 已删除；口令未进 git

### A-E2E

本工单无 UI 改动，无 A-E2E。未在智能座舱 POC 实机执行 load（需 MFA）。

---

## 二、人工签字 / 主观

无。POC 实装由接手人按检查单自测。

---

## 三、不在本工单范围

- 改堡垒机账号绑定（CI）
- 在 POC 上代为 docker run
- 把 Word 里的密码写入仓库

---

## 四、点测结论

- [x] A-1 — 可标 done
- [x] 无 A-E2E / 无 H
