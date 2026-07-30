import { DatabaseOutlined, LockOutlined, UserOutlined } from '@ant-design/icons'
import { Alert, Button, Form, Input, Spin, Typography } from 'antd'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { api } from '../api'
import { useAuth } from '../auth/AuthContext'
import { APP_NAME, APP_TAGLINE } from '../config/app'

type RegisterForm = {
  username: string
  password: string
  confirm: string
  display_name?: string
}

export function RegisterPage() {
  const { user, loading, completeSession } = useAuth()
  const navigate = useNavigate()
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (user) {
      navigate('/', { replace: true })
    }
  }, [user, navigate])

  if (loading) {
    return (
      <div className="login-page">
        <Spin size="large" tip="加载中…" />
      </div>
    )
  }

  if (user) {
    return <Navigate to="/" replace />
  }

  const onFinish = async (values: RegisterForm) => {
    if (values.password !== values.confirm) {
      setError('两次输入的密码不一致')
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      const res = await api.register({
        username: values.username.trim(),
        password: values.password,
        display_name: values.display_name?.trim() || undefined,
      })
      completeSession(res, res.message)
      navigate('/', { replace: true })
    } catch (e) {
      const msg =
        (e as { response?: { data?: { detail?: { message?: string } | string } } })?.response?.data
          ?.detail
      if (typeof msg === 'object' && msg?.message) {
        setError(msg.message)
      } else if (typeof msg === 'string') {
        setError(msg)
      } else {
        setError('注册失败，请稍后重试')
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
          注册 · {APP_NAME}
        </Typography.Title>
        <Typography.Paragraph className="login-card__subtitle">{APP_TAGLINE}</Typography.Paragraph>

        {error ? (
          <Alert type="error" message={error} showIcon style={{ marginBottom: 16 }} />
        ) : null}
        <Form<RegisterForm> layout="vertical" onFinish={onFinish} autoComplete="off" requiredMark={false}>
          <Form.Item
            name="username"
            label="用户名"
            rules={[{ required: true, message: '请输入用户名' }]}
          >
            <Input prefix={<UserOutlined />} placeholder="登录名" autoFocus size="large" />
          </Form.Item>
          <Form.Item name="display_name" label="显示名（可选）">
            <Input placeholder="在界面中展示的名称" size="large" />
          </Form.Item>
          <Form.Item
            name="password"
            label="密码"
            rules={[
              { required: true, message: '请输入密码' },
              { min: 8, message: '至少 8 位' },
            ]}
          >
            <Input.Password prefix={<LockOutlined />} placeholder="••••••••" size="large" />
          </Form.Item>
          <Form.Item
            name="confirm"
            label="确认密码"
            rules={[{ required: true, message: '请再次输入密码' }]}
          >
            <Input.Password prefix={<LockOutlined />} placeholder="••••••••" size="large" />
          </Form.Item>
          <Form.Item style={{ marginBottom: 8, marginTop: 8 }}>
            <Button type="primary" htmlType="submit" block loading={submitting} size="large">
              注册
            </Button>
          </Form.Item>
          <Typography.Paragraph type="secondary" style={{ textAlign: 'center', marginBottom: 0 }}>
            已有账号？ <Link to="/login">去登录</Link>
          </Typography.Paragraph>
        </Form>
      </div>
    </div>
  )
}
