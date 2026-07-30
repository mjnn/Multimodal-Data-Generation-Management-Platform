import { App, Button, Form, Input, Modal, Space, Tag, Typography } from 'antd'
import { useEffect, useState } from 'react'
import { api } from '../api'
import { useAuth } from '../auth/AuthContext'
import { ROLE_LABELS } from '../auth/roles'
import type { AppRole } from '../auth/types'

type Props = {
  open: boolean
  onClose: () => void
}

function formatRoleLabel(role: string): string {
  return ROLE_LABELS[role as AppRole] ?? role
}

export function UserAccountModal({ open, onClose }: Props) {
  const { message } = App.useApp()
  const { user, refreshMe } = useAuth()
  const [profileForm] = Form.useForm<{ display_name: string }>()
  const [passwordForm] = Form.useForm<{ current_password: string; new_password: string; confirm: string }>()
  const [savingProfile, setSavingProfile] = useState(false)
  const [savingPassword, setSavingPassword] = useState(false)

  useEffect(() => {
    if (open && user) {
      profileForm.setFieldsValue({ display_name: user.display_name })
      passwordForm.resetFields()
    }
  }, [open, user, profileForm, passwordForm])

  if (!user) return null

  const onSaveProfile = async () => {
    const values = await profileForm.validateFields()
    setSavingProfile(true)
    try {
      await api.updateMe({ display_name: values.display_name.trim() })
      await refreshMe()
      message.success('显示名称已更新')
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : '更新失败')
    } finally {
      setSavingProfile(false)
    }
  }

  const onChangePassword = async () => {
    const values = await passwordForm.validateFields()
    if (values.new_password !== values.confirm) {
      message.error('两次输入的新密码不一致')
      return
    }
    setSavingPassword(true)
    try {
      await api.changePassword(values.current_password, values.new_password)
      passwordForm.resetFields()
      message.success('密码已修改')
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : '修改密码失败')
    } finally {
      setSavingPassword(false)
    }
  }

  return (
    <Modal title="账号信息" open={open} onCancel={onClose} footer={null} width={480} destroyOnClose>
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        <div>
          <Typography.Text type="secondary">用户名</Typography.Text>
          <Typography.Paragraph style={{ marginBottom: 4 }}>{user.username}</Typography.Paragraph>
          <Space size={4} wrap>
            {(user.roles).map((role) => (
              <Tag key={role}>{formatRoleLabel(role)}</Tag>
            ))}
          </Space>
        </div>

        <Form form={profileForm} layout="vertical" onFinish={() => void onSaveProfile()}>
          <Form.Item
            label="显示名称"
            name="display_name"
            rules={[{ required: true, message: '请输入显示名称' }]}
          >
            <Input maxLength={64} />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={savingProfile}>
            保存名称
          </Button>
        </Form>

        <Typography.Title level={5} style={{ margin: 0 }}>
          修改密码
        </Typography.Title>
        <Form form={passwordForm} layout="vertical" onFinish={() => void onChangePassword()}>
          <Form.Item
            label="当前密码"
            name="current_password"
            rules={[{ required: true, message: '请输入当前密码' }]}
          >
            <Input.Password autoComplete="current-password" />
          </Form.Item>
          <Form.Item
            label="新密码"
            name="new_password"
            rules={[
              { required: true, message: '请输入新密码' },
              { min: 8, message: '至少 8 位' },
            ]}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Form.Item
            label="确认新密码"
            name="confirm"
            rules={[{ required: true, message: '请再次输入新密码' }]}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Button htmlType="submit" loading={savingPassword}>
            更新密码
          </Button>
        </Form>
      </Space>
    </Modal>
  )
}
