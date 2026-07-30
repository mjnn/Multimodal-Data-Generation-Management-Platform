import { PlusOutlined, SaveOutlined, SettingOutlined } from '@ant-design/icons'
import { Alert, Button, Form, Input, Space, Table, Typography, message } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useCallback, useEffect, useState } from 'react'
import { api } from '../api'
import type { SystemEnvVariable } from '../api/types'
import { ContentCard, PageHeader, PageStack } from '../components/ui'

type Row = SystemEnvVariable & { rowKey: string }

export function SystemEnvPage() {
  const [meta, setMeta] = useState<{
    path: string
    writable: boolean
    restart_required_hint?: string
  } | null>(null)
  const [rows, setRows] = useState<Row[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm<{ customKey?: string; customValue?: string }>()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await api.getSystemEnv()
      setMeta({
        path: res.path,
        writable: res.writable,
        restart_required_hint: res.restart_required_hint,
      })
      setRows(
        res.variables.map((v) => ({
          ...v,
          rowKey: v.key,
        })),
      )
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : '加载系统参数失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const updateRow = (key: string, value: string) => {
    setRows((prev) => prev.map((r) => (r.key === key ? { ...r, value } : r)))
  }

  const addCustomRow = () => {
    const key = form.getFieldValue('customKey')?.trim()
    const value = form.getFieldValue('customValue') ?? ''
    if (!key) {
      message.warning('请输入变量名')
      return
    }
    if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(key)) {
      message.warning('变量名格式无效')
      return
    }
    if (rows.some((r) => r.key === key)) {
      message.warning('变量已存在')
      return
    }
    setRows((prev) => [
      ...prev,
      { key, value, sensitive: /SECRET|PASSWORD|KEY|TOKEN/i.test(key), in_catalog: false, rowKey: key },
    ])
    form.resetFields(['customKey', 'customValue'])
  }

  const onSave = async () => {
    if (!meta?.writable) {
      message.error('当前环境文件不可写')
      return
    }
    setSaving(true)
    try {
      const env: Record<string, string | null> = {}
      for (const r of rows) {
        env[r.key] = r.value.trim() === '' ? null : r.value
      }
      const res = await api.saveSystemEnv({ env })
      message.success('系统参数已保存')
      setMeta({
        path: res.path,
        writable: res.writable,
        restart_required_hint: res.restart_required_hint,
      })
      setRows(res.variables.map((v) => ({ ...v, rowKey: v.key })))
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const columns: ColumnsType<Row> = [
    {
      title: '变量名',
      dataIndex: 'key',
      width: 240,
      render: (key: string, r) => (
        <Space direction="vertical" size={0}>
          <Typography.Text code style={{ fontSize: 12 }}>
            {key}
          </Typography.Text>
          {!r.in_catalog ? (
            <Typography.Text type="secondary" style={{ fontSize: 11 }}>
              自定义
            </Typography.Text>
          ) : null}
        </Space>
      ),
    },
    {
      title: '值',
      dataIndex: 'value',
      render: (_v, r) =>
        r.sensitive ? (
          <Input.Password
            visibilityToggle
            size="small"
            value={r.value}
            placeholder="留空表示删除该变量"
            onChange={(e) => updateRow(r.key, e.target.value)}
            autoComplete="off"
          />
        ) : (
          <Input
            size="small"
            value={r.value}
            placeholder="留空表示删除该变量"
            onChange={(e) => updateRow(r.key, e.target.value)}
            autoComplete="off"
          />
        ),
    },
  ]

  return (
    <PageStack>
      <PageHeader
        title="系统参数管理"
        description="编辑项目环境变量（.env / 运行时 project.env）。敏感项请谨慎修改。"
        icon={<SettingOutlined />}
        extra={
          <Button
            type="primary"
            icon={<SaveOutlined />}
            loading={saving}
            disabled={!meta?.writable}
            onClick={() => void onSave()}
          >
            保存
          </Button>
        }
      />

      {meta ? (
        <Alert
          type={meta.writable ? 'info' : 'warning'}
          showIcon
          message={
            <>
              配置文件：<Typography.Text code>{meta.path}</Typography.Text>
              {!meta.writable ? '（不可写）' : null}
            </>
          }
          description={meta.restart_required_hint}
          style={{ marginBottom: 0 }}
        />
      ) : null}

      <ContentCard title="环境变量" noPadding>
        <Table<Row>
          rowKey="rowKey"
          loading={loading}
          columns={columns}
          dataSource={rows}
          pagination={{ pageSize: 20, showSizeChanger: true, pageSizeOptions: ['20', '50', '100'] }}
          size="small"
        />
      </ContentCard>

      <ContentCard title="添加变量">
        <Form form={form} layout="inline" onFinish={() => addCustomRow()}>
          <Form.Item name="customKey" label="变量名">
            <Input placeholder="HMI_EXAMPLE" style={{ width: 220 }} />
          </Form.Item>
          <Form.Item name="customValue" label="值">
            <Input placeholder="可选" style={{ width: 280 }} />
          </Form.Item>
          <Form.Item>
            <Button htmlType="submit" icon={<PlusOutlined />}>
              添加
            </Button>
          </Form.Item>
        </Form>
      </ContentCard>
    </PageStack>
  )
}
