import { PlusOutlined, TeamOutlined } from '@ant-design/icons'
import {
  Button,
  Form,
  Input,
  Modal,
  Select,
  Switch,
  Table,
  Tag,
  message,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useCallback, useEffect, useState } from 'react'
import { api } from '../api'
import { ALL_ROLES, ROLE_LABELS } from '../auth/roles'
import type { AppRole, AuthUser } from '../auth/types'
import { ContentCard, PageHeader, PageStack } from '../components/ui'

type UserRow = AuthUser

type UserForm = {
  username?: string
  password?: string
  display_name?: string
  roles: AppRole[]
  is_active: boolean
}

export function AdminUsersPage() {
  const [users, setUsers] = useState<UserRow[]>([])
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<UserRow | null>(null)
  const [form] = Form.useForm<UserForm>()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setUsers(await api.listAdminUsers())
    } catch {
      message.error('加载用户列表失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const openCreate = () => {
    setEditing(null)
    form.setFieldsValue({ roles: ['reviewer'], is_active: true })
    setModalOpen(true)
  }

  const openEdit = (row: UserRow) => {
    setEditing(row)
    form.setFieldsValue({
      display_name: row.display_name,
      roles: row.roles,
      is_active: row.is_active,
    })
    setModalOpen(true)
  }

  const onSubmit = async () => {
    const values = await form.validateFields()
    try {
      if (editing) {
        await api.updateAdminUser(editing.id, {
          display_name: values.display_name,
          roles: values.roles,
          is_active: values.is_active,
          password: values.password || undefined,
        })
        message.success('用户已更新')
      } else {
        await api.createAdminUser({
          username: values.username!,
          password: values.password!,
          display_name: values.display_name,
          roles: values.roles,
        })
        message.success('用户已创建')
      }
      setModalOpen(false)
      form.resetFields()
      await load()
    } catch (e) {
      const detail = (e as { response?: { data?: { detail?: { message?: string } } } })?.response
        ?.data?.detail?.message
      message.error(detail ?? '操作失败')
    }
  }

  const columns: ColumnsType<UserRow> = [
    { title: '用户名', dataIndex: 'username', key: 'username' },
    { title: '显示名', dataIndex: 'display_name', key: 'display_name' },
    {
      title: '角色',
      dataIndex: 'roles',
      key: 'roles',
      render: (roles: AppRole[]) =>
        roles.length ? (
          roles.map((r) => (
            <Tag key={r} color={r === 'admin' ? 'red' : r === 'anonymous' ? 'default' : 'blue'}>
              {ROLE_LABELS[r] ?? r}
            </Tag>
          ))
        ) : (
          <Tag color="default">匿名（待分配）</Tag>
        ),
    },
    {
      title: '状态',
      dataIndex: 'is_active',
      key: 'is_active',
      render: (active: boolean) =>
        active ? <Tag color="success">启用</Tag> : <Tag color="default">禁用</Tag>,
    },
    {
      title: '操作',
      key: 'actions',
      render: (_, row) => (
        <Button type="link" size="small" onClick={() => openEdit(row)}>
          编辑
        </Button>
      ),
    },
  ]

  return (
    <PageStack>
      <PageHeader
        title="用户与角色管理"
        description="自助注册默认为匿名用户（仅数据总览）；请在此为用户分配业务角色（如 reviewer、pipeline_manager）。"
        icon={<TeamOutlined />}
        extra={
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
            新建用户
          </Button>
        }
      />

      <ContentCard noPadding>
        <Table rowKey="id" loading={loading} columns={columns} dataSource={users} pagination={false} />
      </ContentCard>

      <Modal
        title={editing ? `编辑用户 · ${editing.username}` : '新建用户'}
        open={modalOpen}
        onCancel={() => {
          setModalOpen(false)
          form.resetFields()
        }}
        onOk={() => void onSubmit()}
        destroyOnHidden
        width={480}
      >
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
          {!editing ? (
            <>
              <Form.Item
                name="username"
                label="用户名"
                rules={[{ required: true, message: '请输入用户名' }]}
              >
                <Input />
              </Form.Item>
              <Form.Item
                name="password"
                label="密码"
                rules={[
                  { required: true, message: '请输入密码' },
                  { min: 8, message: '至少 8 位' },
                ]}
              >
                <Input.Password />
              </Form.Item>
            </>
          ) : (
            <Form.Item
              name="password"
              label="重置密码（可选）"
              rules={[
                {
                  validator: (_, value) =>
                    !value || String(value).length >= 8
                      ? Promise.resolve()
                      : Promise.reject(new Error('至少 8 位')),
                },
              ]}
            >
              <Input.Password placeholder="留空则不修改" />
            </Form.Item>
          )}
          <Form.Item name="display_name" label="显示名">
            <Input />
          </Form.Item>
          <Form.Item
            name="roles"
            label="角色"
            rules={[{ required: true, message: '请选择至少一个角色' }]}
          >
            <Select
              mode="multiple"
              options={ALL_ROLES.map((r) => ({ value: r, label: ROLE_LABELS[r] }))}
            />
          </Form.Item>
          {editing ? (
            <Form.Item name="is_active" label="启用" valuePropName="checked">
              <Switch />
            </Form.Item>
          ) : null}
        </Form>
      </Modal>
    </PageStack>
  )
}
