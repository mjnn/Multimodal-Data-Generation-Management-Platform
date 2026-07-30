import {
  ApartmentOutlined,
  CheckCircleOutlined,
  CloudServerOutlined,
  DatabaseOutlined,
  DeploymentUnitOutlined,
  FolderOpenOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  SettingOutlined,
  TeamOutlined,
} from '@ant-design/icons'
import { Breadcrumb, Button, Dropdown, Layout, Menu, Typography } from 'antd'
import type { MenuProps } from 'antd'
import { useMemo, useState, type ReactNode } from 'react'
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import {
  canAccessDatasets,
  canAccessOss,
  canAccessPipeline,
  canAccessReview,
  canManageTaxonomy,
  canManageUsers,
  canSwitchDataSource,
} from '../auth/roles'
import { APP_NAME, APP_NAME_SHORT, APP_TAGLINE } from '../config/app'
import { LocalModeControls } from '../components/LocalModeControls'
import { ThemeToggle } from '../components/ThemeToggle'
import { UserAccountModal } from '../components/UserAccountModal'
import { useThemeMode } from '../context/ThemeContext'
import { parseReviewV2OpenMode } from '../utils/reviewConfidence'

const { Header, Sider, Content } = Layout

const ROUTE_LABELS: Record<string, string> = {
  '/': '数据总览',
  '/pipeline': '管线管理',
  '/oss': 'OSS 管理',
  '/review': '校核任务',
  '/review/confidence': '置信度校核',
  '/review/disputes': '置信度校核',
  '/review/tasks': '任务领取',
  '/review/assignments': '任务派发',
  '/review/workbench': '校核工作台',
  '/datasets': '数据集',
  '/taxonomy': '标签树',
  '/admin/users': '用户管理',
  '/admin/system-env': '系统参数管理',
}

function buildBreadcrumbs(pathname: string, search: string): { title: ReactNode }[] {
  const items: { title: ReactNode }[] = [{ title: <Link to="/">{APP_NAME}</Link> }]

  if (pathname.startsWith('/clips/')) {
    items.push({ title: <Link to="/">数据总览</Link> })
    items.push({ title: 'Clip 时间轴' })
    return items
  }

  if (pathname.startsWith('/review/workbench')) {
    const openMode = parseReviewV2OpenMode(new URLSearchParams(search).get('mode'))
    items.push({ title: <Link to={openMode ? '/review/confidence' : '/review/tasks'}>校核任务</Link> })
    items.push({ title: openMode ? '置信度校核工作台' : '校核工作台' })
    return items
  }

  if (pathname.startsWith('/review/')) {
    items.push({ title: <Link to="/review/confidence">校核任务</Link> })
    const sub = ROUTE_LABELS[pathname]
    if (sub && pathname !== '/review/confidence' && pathname !== '/review/disputes') {
      items.push({ title: sub })
    } else if (pathname === '/review/confidence' || pathname === '/review/disputes') {
      items.push({ title: '置信度校核' })
    }
    return items
  }

  if (pathname.startsWith('/datasets/') && pathname !== '/datasets') {
    items.push({ title: <Link to="/datasets">数据集</Link> })
    items.push({ title: '快照详情' })
    return items
  }

  if (pathname.startsWith('/taxonomy/') && pathname !== '/taxonomy') {
    items.push({ title: <Link to="/taxonomy">标签树</Link> })
    items.push({ title: '版本编辑' })
    return items
  }

  const label = ROUTE_LABELS[pathname]
  if (label) {
    items.push({ title: label })
  }

  return items
}

export function AppLayout() {
  const navigate = useNavigate()
  const location = useLocation()
  const { user, logout } = useAuth()
  const { mode: themeMode } = useThemeMode()
  const [collapsed, setCollapsed] = useState(false)
  const [accountOpen, setAccountOpen] = useState(false)

  const navItems: MenuProps['items'] = useMemo(() => {
    const roles = user?.roles
    const browse: MenuProps['items'] = [{ key: '/', icon: <DatabaseOutlined />, label: '数据总览' }]

    const workflow: MenuProps['items'] = []
    if (canAccessPipeline(roles)) {
      workflow.push({ key: '/pipeline', icon: <DeploymentUnitOutlined />, label: '管线管理' })
    }
    if (canAccessOss(roles)) {
      workflow.push({ key: '/oss', icon: <CloudServerOutlined />, label: 'OSS 管理' })
    }
    if (canAccessReview(roles)) {
      workflow.push({ key: '/review/confidence', icon: <CheckCircleOutlined />, label: '校核任务' })
    }
    if (canAccessDatasets(roles)) {
      workflow.push({ key: '/datasets', icon: <FolderOpenOutlined />, label: '数据集' })
    }

    const admin: MenuProps['items'] = []
    if (canManageTaxonomy(roles)) {
      admin.push({ key: '/taxonomy', icon: <ApartmentOutlined />, label: '标签树' })
    }
    if (canManageUsers(roles)) {
      admin.push({ key: '/admin/users', icon: <TeamOutlined />, label: '用户管理' })
      admin.push({ key: '/admin/system-env', icon: <SettingOutlined />, label: '系统参数管理' })
    }

    const groups: MenuProps['items'] = [
      { type: 'group', label: '数据浏览', children: browse },
    ]
    if (workflow.length > 0) {
      groups.push({ type: 'group', label: '管线工作', children: workflow })
    }
    if (admin.length > 0) {
      groups.push({ type: 'group', label: '系统管理', children: admin })
    }
    return groups
  }, [user?.roles])

  const flatKeys = useMemo(() => {
    const keys: string[] = []
    for (const item of navItems ?? []) {
      if (item && 'children' in item && item.children) {
        for (const child of item.children) {
          if (child && 'key' in child && child.key) keys.push(String(child.key))
        }
      }
    }
    return keys
  }, [navItems])

  const selected =
    flatKeys.find((k) => k !== '/' && location.pathname.startsWith(k)) ??
    (location.pathname.startsWith('/upload') && flatKeys.includes('/pipeline') ? '/pipeline' : undefined) ??
    (location.pathname.startsWith('/clips') ? '/' : undefined) ??
    (location.pathname.startsWith('/review') ? '/review/confidence' : '/')

  const breadcrumbs = buildBreadcrumbs(location.pathname, location.search)
  const userInitial = (user?.display_name ?? user?.username ?? '?').slice(0, 1).toUpperCase()

  return (
    <Layout className="app-shell">
      <Sider
        className="app-shell__sider"
        width={240}
        theme={themeMode === 'dark' ? 'dark' : 'light'}
        breakpoint="lg"
        collapsedWidth={64}
        collapsible
        collapsed={collapsed}
        onCollapse={setCollapsed}
        trigger={null}
      >
        <div className="app-shell__brand">
          {!collapsed ? (
            <>
              <Typography.Title level={4} className="app-shell__brand-title">
                {APP_NAME}
              </Typography.Title>
              <Typography.Text className="app-shell__brand-sub">{APP_TAGLINE}</Typography.Text>
              {canSwitchDataSource(user?.roles) ? <LocalModeControls /> : null}
            </>
          ) : (
            <>
              <Typography.Title level={4} className="app-shell__brand-title" style={{ fontSize: 14 }}>
                {APP_NAME_SHORT}
              </Typography.Title>
              {canSwitchDataSource(user?.roles) ? <LocalModeControls collapsed /> : null}
            </>
          )}
        </div>
        <Menu
          className="app-shell__menu"
          theme={themeMode === 'dark' ? 'dark' : 'light'}
          mode="inline"
          selectedKeys={[selected]}
          items={navItems}
          onClick={({ key }) => navigate(key)}
        />
      </Sider>
      <Layout>
        <Header className="app-shell__header">
          <div className="app-shell__header-left">
            <Button
              type="text"
              className="app-shell__collapse-btn"
              icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
              onClick={() => setCollapsed((v) => !v)}
              aria-label={collapsed ? '展开侧栏' : '收起侧栏'}
            />
            <Breadcrumb items={breadcrumbs} />
            <span className="app-shell__header-meta">Clip 级校核 · MP4 预览</span>
          </div>
          <div className="app-shell__user">
            <ThemeToggle />
            <Dropdown
              menu={{
                items: [
                  { key: 'profile', label: '账号信息' },
                  { type: 'divider' },
                  { key: 'logout', label: '退出登录', danger: true },
                ],
                onClick: ({ key }) => {
                  if (key === 'profile') setAccountOpen(true)
                  if (key === 'logout') void logout()
                },
              }}
              trigger={['click']}
            >
              <button type="button" className="app-shell__avatar-btn" aria-label="用户菜单">
                <span className="app-shell__avatar" aria-hidden>
                  {userInitial}
                </span>
                <Typography.Text>{user?.display_name ?? user?.username}</Typography.Text>
              </button>
            </Dropdown>
          </div>
        </Header>
        <Content className="app-shell__content">
          <Outlet />
        </Content>
        <UserAccountModal open={accountOpen} onClose={() => setAccountOpen(false)} />
      </Layout>
    </Layout>
  )
}
