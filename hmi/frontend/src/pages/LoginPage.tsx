import { DatabaseOutlined, LockOutlined, UserOutlined } from '@ant-design/icons'
import { Alert, Button, Form, Input, Spin, Typography } from 'antd'
import { useEffect, useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { APP_NAME, APP_TAGLINE } from '../config/app'

type LoginForm = {
  username: string
  password: string
}

export function LoginPage() {
  const { user, login, loading } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const from = (location.state as { from?: string } | null)?.from ?? '/'

  useEffect(() => {
    if (user) {
      navigate(from, { replace: true })
    }
  }, [user, from, navigate])

  if (loading) {
    return (
      <div className="login-page">
        <Spin size="large" tip="加载中…" />
      </div>
    )
  }

  if (user) {
    return <Navigate to={from} replace />
  }

  const onFinish = async (values: LoginForm) => {
    setSubmitting(true)
    setError(null)
    try {
      await login(values.username.trim(), values.password)
      navigate(from, { replace: true })
    } catch (e) {
      const msg =
        (e as { response?: { data?: { detail?: { message?: string } | string } } })?.response?.data
          ?.detail
      if (typeof msg === 'object' && msg?.message) {
        setError(msg.message)
      } else if (typeof msg === 'string') {
        setError(msg)
      } else {
        setError('登录失败，请检查用户名和密码')
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-card__logo" aria-hidden>
          <DatabaseOutlined />
        </div>
        <Typography.Title level={3} className="login-card__title">
          {APP_NAME}
        </Typography.Title>
        <Typography.Paragraph className="login-card__subtitle">
          {APP_TAGLINE}
        </Typography.Paragraph>

        {error ? (
          <Alert type="error" message={error} showIcon style={{ marginBottom: 16 }} />
        ) : null}

        <Form<LoginForm> layout="vertical" onFinish={onFinish} autoComplete="off" requiredMark={false}>
          <Form.Item
            name="username"
            label="用户名"
            rules={[{ required: true, message: '请输入用户名' }]}
          >
            <Input prefix={<UserOutlined />} placeholder="admin" autoFocus size="large" />
          </Form.Item>
          <Form.Item
            name="password"
            label="密码"
            rules={[{ required: true, message: '请输入密码' }]}
          >
            <Input.Password prefix={<LockOutlined />} placeholder="••••••••" size="large" />
          </Form.Item>
          <Form.Item style={{ marginBottom: 0, marginTop: 8 }}>
            <Button type="primary" htmlType="submit" block loading={submitting} size="large">
              登录
            </Button>
          </Form.Item>
        </Form>
      </div>
    </div>
  )
}
