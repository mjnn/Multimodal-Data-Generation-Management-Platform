# M1 实现说明 — 认证 + 用户管理 + 路由门禁

| 字段 | 内容 |
|------|------|
| 版本 | v1.0 |
| 对应 PRD | v0.2 |
| 里程碑 | **M1** |
| 目标一句话 | 四类角色可登录，现有 HMI 页在门禁后按角色可用 |
| 前置 | PRD v0.2 缺口评审 P0=0 |

---

## 1. 范围

### 1.1 必做（Done 定义）

| # | 能力 | 对应 PRD |
|---|------|----------|
| 1 | 应用 DB（SQLite `hmi/data/app.db`）用户与角色表 | §5.1 `app_user` / `app_user_role` |
| 2 | JWT 登录 / 登出 / 当前用户 | §11.1 |
| 3 | 现有 API 加认证中间件（health 除外） | §10、§11.5 |
| 4 | 管理员用户 CRUD + 角色授予 | §3、§11.1 |
| 5 | `hmi/scripts/bootstrap_admin.py` 初始化首个 admin | R6 |
| 6 | 前端 `/login` + Auth Context + 受保护路由 | §8 |
| 7 | 按角色渲染侧边栏；OSS 仅 admin / dataset_manager | §3、§8 |
| 8 | 登录后现有 Clip/Search/Overview 不退化 | S6 |

### 1.2 明确不做（留给 M2+）

- Taxonomy DB / 编辑器 / YAML 导入
- Clip 校核队列与 `clip_label_review`
- Dataset 快照与导出
- `audit_log` 表（M3 起与校核一并落库）
- SSO / LDAP / 多租户
- PostgreSQL 迁移（可留配置钩子，M1 仅 SQLite）

### 1.3 已拍板决策

| # | 决策 |
|---|------|
| D1 | JWT access 30min；refresh 7d；M1 优先 **httpOnly cookie** 存 refresh，access 放 memory + Authorization 备选 |
| D2 | 应用 DB 路径 `hmi/data/app.db`，与 `timeline.db` 并列 |
| D3 | 角色枚举固定四值：`admin` \| `reviewer` \| `dataset_manager` \| `model_trainer` |
| D4 | 单用户可多角色（`app_user_role` 多行） |
| D5 | 未实现的路由（/taxonomy、/review、/datasets）M1 **不出现在菜单**，避免空页抢跑 |
| D6 | `/api/health` 保持公开；`/api/auth/login` 公开 |

### 1.4 本里程碑验收切片（来自 PRD 附录 C）

- [ ] **C1** admin 创建 reviewer 并可登录
- [ ] **C8** 登录后 Clip 浏览/检索正常
- [ ] **N1** 未登录 `/api/clips` → 401
- [ ] **N2** reviewer 调 `POST /admin/users` → 403

---

## 2. 状态机子集

本里程碑不涉及业务状态机；用户仅有 `is_active`：

| 状态 | 说明 |
|------|------|
| active | 可登录 |
| disabled | `is_active=false`，登录拒绝 |

---

## 3. 数据模型（本阶段落表）

### 3.1 `app_user`

```sql
CREATE TABLE app_user (
  id TEXT PRIMARY KEY,
  username TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  display_name TEXT,
  is_active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
```

### 3.2 `app_user_role`

```sql
CREATE TABLE app_user_role (
  user_id TEXT NOT NULL REFERENCES app_user(id),
  role TEXT NOT NULL CHECK (role IN ('admin','reviewer','dataset_manager','model_trainer')),
  PRIMARY KEY (user_id, role)
);
```

### 3.3 迁移

- 模块：`hmi/backend/hmi/app_db.py`（init + session）
- 启动时 `ensure_schema()`；无 Alembic（M1 保持简单）

---

## 4. API 子集

### 4.1 本阶段实现

| Method | Path | 角色 |
|--------|------|------|
| POST | `/api/auth/login` | 公开 |
| POST | `/api/auth/logout` | 已登录 |
| POST | `/api/auth/refresh` | refresh cookie |
| GET | `/api/auth/me` | 已登录 |
| POST | `/api/admin/users` | admin |
| GET | `/api/admin/users` | admin |
| PATCH | `/api/admin/users/{id}` | admin |

### 4.2 本阶段加门禁、不改动业务逻辑

现有 `/api/clips/*`、`/api/search/*`、`/api/oss/*`、`/api/upload/*` 等 — 需有效 JWT；OSS 写操作额外校验 admin 或 dataset_manager。

### 4.3 明确不实现

- `/api/taxonomy/*`
- `/api/review/*`
- `/api/datasets/*`

---

## 5. 前端页面（本阶段）

| 路由 | 组件 | 说明 |
|------|------|------|
| `/login` | `LoginPage` | 用户名密码表单 |
| `/admin/users` | `AdminUsersPage` | 用户列表 + 创建/编辑抽屉 |
| 现有四页 | 加 `RequireAuth` 包裹 | Overview / Clip / Search / OSS |

### 5.1 菜单可见性（M1）

| 菜单项 | admin | reviewer | dataset_manager | model_trainer |
|--------|:-----:|:--------:|:---------------:|:-------------:|
| Clip 总览 | ✓ | ✓ | ✓ | ✓ |
| 标签检索 | ✓ | ✓ | ✓ | ✓ |
| OSS 管理 | ✓ | — | ✓ | — |
| 用户管理 | ✓ | — | — | — |

---

## 6. 工单表

| ID | 名称 | 依赖 | 产出 |
|----|------|------|------|
| M1.1 | 应用 DB + JWT 认证后端 | DOC-M1 | `app_db.py`、`auth` 路由、API 中间件 |
| M1.2 | 管理员用户 API + bootstrap | M1.1 | `/admin/users`、`bootstrap_admin.py` |
| M1.3 | 前端登录与 Auth 上下文 | M1.1 | `LoginPage`、token/cookie、axios 拦截器 |
| M1.4 | 路由门禁 + 角色菜单 + OSS 权限 | M1.2, M1.3 | `RequireAuth`、`AdminUsersPage`、菜单矩阵 |
| M1.5 | M1 验收与加固 | M1.4 | `acceptance/M1.md`、负向用例通过 |

---

## 7. 测试最低集

| 类型 | 内容 |
|------|------|
| API | login 成功/失败；me；admin 创建用户；reviewer 403 admin |
| 中间件 | 无 token 访问 `/api/clips` → 401 |
| 前端构建 | `npm run build` 无 TS 错误 |
| 手工 | 附录 C M1 切片四条 |

---

## 8. 完成口径

**M1 出口**：bootstrap admin 可登录 → 创建 reviewer → 两角色菜单差异正确 → 登录后原 HMI 四页可用 → N1/N2 通过。  
验收文件：`project-management/acceptance/M1.md`

---

## 9. 技术落点参考（现有代码）

| 区域 | 路径 |
|------|------|
| FastAPI 入口 | `hmi/backend/hmi/main.py`、`router.py` |
| 前端路由 | `frontend/src/App.tsx` |
| 布局/菜单 | `frontend/src/layouts/AppLayout.tsx` |
| API 客户端 | `frontend/src/api/index.ts` |
