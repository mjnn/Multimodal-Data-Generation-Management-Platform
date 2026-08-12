# 验收 · HMI 测试模式开关 + 重置测试数据

> 日期：2026-08-11  
> 范围：`HMI_TEST_MODE`、OSS 管理页「重置测试数据」、云端 MC+OSS 全量重置

## A · 单元 / API / 构建

| 编号 | 结果 | 证据 |
|------|------|------|
| A-1 | pass | `py -3 hmi/backend/scripts/test_test_mode_reset.py -v` → 3/3 OK（flag 真值、重置非测试模式 PermissionError） |
| A-2 | pass | `node ./node_modules/typescript/bin/tsc --noEmit -p hmi/frontend/tsconfig.json` exit 0 |

## A-E2E · Playwright / Selenium

| 编号 | 结果 | 证据 |
|------|------|------|
| A-E2E-1 | skip | 本工单未新增 Playwright；UI 路径可脚本化项留待后续补（系统参数 Switch、OSS 页按钮显隐） |

## H · 人工签字

| 编号 | 摘要 |
|------|------|
| H-1 | 系统参数打开 `HMI_TEST_MODE` → 侧栏出现本地/云端切换与重置；关闭后强制云端、按钮隐藏 |
| H-2 | 测试模式+云端下点「重置测试数据」：确认文案含 MC/OSS；执行后管线产物清空（慎用生产桶） |

### 操作提示

1. **系统参数管理** → `HMI_TEST_MODE` 开关 → 保存（自动刷新）
2. 开：侧栏切换 + 「重置测试数据」；OSS 管理页标题栏（admin）同按钮
3. 关：仅云端；切换与重置均不可见；API 切 local / 重置返回 403
