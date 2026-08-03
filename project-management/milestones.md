# 里程碑入口 / 出口标准

对应 PRD §12。出口以 **用户点测** + `acceptance/M{N}.md` 为准。

---

## M1 · 认证 + 用户管理 + 路由门禁

| | |
|---|---|
| **入口** | PRD v0.2 P0=0；`docs/m1-implementation-notes.md` 已发布 |
| **出口** | C1、C8、N1、N2 通过；`acceptance/M1.md` 用户确认 |
| **成功标准** | S1（部分）、S6 |
| **禁止** | 不得开始 Taxonomy / 校核 / Dataset 业务代码 |

---

## M2 · Taxonomy 版本树

| | |
|---|---|
| **入口** | M1 出口；`docs/m2-implementation-notes.md`（M1 出口后编写） |
| **出口** | S2；draft→publish 可点测；YAML 导入 v1 |
| **禁止** | 不得开始校核队列、Dataset |

---

## M3 · Clip 校核

| | |
|---|---|
| **入口** | M2 出口；`docs/m3-implementation-notes.md` |
| **出口** | S3；pending→reviewed + audit_log |
| **禁止** | 不得开始 Dataset 导出 |

---

## M4 · Dataset 管理

| | |
|---|---|
| **入口** | M3 出口；`docs/m4-implementation-notes.md` |
| **出口** | S4、S5；OSS + MC 快照 ready |
| **禁止** | 不得实现模型训练 UI |

---

## M5 · 联调与全量验收

| | |
|---|---|
| **入口** | M4 出口 |
| **出口** | PRD 附录 C 正向/负向全通过 |
| **交付** | 更新 WIKI §8 路由表；运维 runbook 补充账号/bootstrap |

---

## M10 · Taxonomy 语义中枢（立项）

| | |
|---|---|
| **入口** | M9 出口；`docs/m10-implementation-notes.md`；P0=0 |
| **出口** | T1–T7；`acceptance/M10.md`；R11–R15 落地 |
| **阶段 U** | `DESIGN-M10.md` · R-UI-M10-1 A−+B **已出口** |
| **禁止** | 自动 publish / 自动改 reviewed y |
