import { Button, Drawer, Form, Input, Modal, Select, Space, Table, Tag, Typography, message } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useCallback, useEffect, useState } from 'react'
import { api } from '../api'
import { useAuth } from '../auth/AuthContext'
import { canManageDatasets, canManageTaxonomy } from '../auth/roles'
import type { TaxonomyProposal } from '../api/types'
import { formatProposalStatus, formatProposalType, PROPOSAL_TYPE_LABELS } from '../utils/uiLabels'

const STATUS_COLOR: Record<string, string> = {
  open: 'processing',
  merged: 'success',
  rejected: 'default',
}

const PROPOSAL_TYPE_OPTIONS = Object.entries(PROPOSAL_TYPE_LABELS).map(([value, label]) => ({
  value,
  label,
}))

type CreateProposalForm = {
  title: string
  proposal_type: string
  target_label_id?: string
  note?: string
}

export function TaxonomyProposalsPanel() {
  const { user } = useAuth()
  const canList = canManageDatasets(user?.roles) || canManageTaxonomy(user?.roles)
  const canCreate = canManageDatasets(user?.roles)
  const canPatch = canManageTaxonomy(user?.roles)

  const [status, setStatus] = useState<string | undefined>('open')
  const [items, setItems] = useState<TaxonomyProposal[]>([])
  const [loading, setLoading] = useState(false)
  const [detail, setDetail] = useState<TaxonomyProposal | null>(null)
  const [createOpen, setCreateOpen] = useState(false)
  const [creating, setCreating] = useState(false)
  const [form] = Form.useForm<CreateProposalForm>()

  const load = useCallback(async () => {
    if (!canList) return
    setLoading(true)
    try {
      const res = await api.listTaxonomyProposals({ status: status || undefined })
      setItems(res.items)
    } catch {
      message.error('加载提案失败')
    } finally {
      setLoading(false)
    }
  }, [canList, status])

  useEffect(() => {
    void load()
  }, [load])

  const patchStatus = async (id: string, next: 'merged' | 'rejected') => {
    try {
      await api.patchTaxonomyProposal(id, { status: next })
      message.success(next === 'merged' ? '已标记合并' : '已拒绝')
      setDetail(null)
      void load()
    } catch {
      message.error('更新失败')
    }
  }

  const submitCreate = async () => {
    const values = await form.validateFields()
    setCreating(true)
    try {
      await api.createTaxonomyProposal({
        title: values.title.trim(),
        proposal_type: values.proposal_type,
        target_label_id: values.target_label_id?.trim() || undefined,
        evidence: {
          source: 'manual',
          note: values.note?.trim() || undefined,
        },
      })
      message.success('提案已创建')
      setCreateOpen(false)
      form.resetFields()
      setStatus('open')
      void load()
    } catch {
      message.error('创建提案失败')
    } finally {
      setCreating(false)
    }
  }

  if (!canList) {
    return (
      <Typography.Text type="secondary">需要数据集管理员或管理员权限查看提案队列。</Typography.Text>
    )
  }

  const columns: ColumnsType<TaxonomyProposal> = [
    { title: '标题', dataIndex: 'title', ellipsis: true },
    {
      title: '类型',
      dataIndex: 'proposal_type',
      width: 120,
      render: (v: string) => <Tag>{formatProposalType(v)}</Tag>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (v: string) => <Tag color={STATUS_COLOR[v] ?? 'default'}>{formatProposalStatus(v)}</Tag>,
    },
    {
      title: '操作',
      key: 'action',
      width: 100,
      render: (_, row) => (
        <Button type="link" size="small" onClick={() => setDetail(row)}>
          详情
        </Button>
      ),
    },
  ]

  return (
    <div data-testid="taxonomy-proposals-panel">
      <Typography.Paragraph type="secondary" style={{ marginBottom: 12, fontSize: 12 }}>
        提案用于记录「标签树应如何改」的建议与证据，<strong>不会自动修改已发布标签树</strong>。
        管理员在草稿版本中手工改树并发布后，在此将提案标记为「已合入草稿」。
      </Typography.Paragraph>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 12, fontSize: 12 }}>
        <strong>如何创建：</strong>
        {canCreate ? (
          <>
            点击「新建提案」填写说明；或调用 API{' '}
            <Typography.Text code>POST /api/taxonomy/proposals</Typography.Text>{' '}
            导入离线聚类结果（类型如相似簇 / 扩展枚举等）。
          </>
        ) : (
          <>请数据集管理员或管理员创建；校核员可在工作中整理需求后交由管理员录入。</>
        )}
      </Typography.Paragraph>
      <Space style={{ marginBottom: 12 }} wrap>
        <Select
          allowClear
          placeholder="状态"
          style={{ width: 140 }}
          value={status}
          onChange={(v) => setStatus(v)}
          options={[
            { value: 'open', label: '待处理' },
            { value: 'merged', label: '已合并' },
            { value: 'rejected', label: '已拒绝' },
          ]}
        />
        <Button onClick={() => void load()}>刷新</Button>
        {canCreate ? (
          <Button type="primary" onClick={() => setCreateOpen(true)}>
            新建提案
          </Button>
        ) : null}
      </Space>
      <Table
        rowKey="id"
        size="small"
        loading={loading}
        columns={columns}
        dataSource={items}
        locale={{
          emptyText: canCreate
            ? '暂无提案。可从标签覆盖率发现缺口后，在此新建提案记录改树建议。'
            : '暂无提案。',
        }}
      />

      <Modal
        title="新建标签树完善提案"
        open={createOpen}
        onCancel={() => {
          setCreateOpen(false)
          form.resetFields()
        }}
        onOk={() => void submitCreate()}
        confirmLoading={creating}
        okText="创建"
        destroyOnClose
      >
        <Form form={form} layout="vertical" initialValues={{ proposal_type: 'other' }}>
          <Form.Item name="title" label="标题" rules={[{ required: true, message: '请输入标题' }]}>
            <Input placeholder="例如：L1.3 天气枚举补充「霾」" />
          </Form.Item>
          <Form.Item name="proposal_type" label="类型" rules={[{ required: true }]}>
            <Select options={PROPOSAL_TYPE_OPTIONS} />
          </Form.Item>
          <Form.Item name="target_label_id" label="目标 label_id">
            <Input placeholder="可选，如 L1.3.weather" />
          </Form.Item>
          <Form.Item name="note" label="说明 / 证据摘要">
            <Input.TextArea rows={3} placeholder="为何改树、涉及哪些 clip、期望如何改…" />
          </Form.Item>
        </Form>
      </Modal>

      <Drawer
        title={detail?.title ?? '提案详情'}
        open={Boolean(detail)}
        onClose={() => setDetail(null)}
        width={520}
        extra={
          canPatch && detail?.status === 'open' ? (
            <Space>
              <Button onClick={() => void patchStatus(detail.id, 'rejected')}>拒绝</Button>
              <Button type="primary" onClick={() => void patchStatus(detail.id, 'merged')}>
                标记已合入草稿
              </Button>
            </Space>
          ) : null
        }
      >
        {detail ? (
          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            <Typography.Text type="secondary">类型：{formatProposalType(detail.proposal_type)}</Typography.Text>
            {detail.target_label_id ? (
              <Typography.Text>目标标签: {detail.target_label_id}</Typography.Text>
            ) : null}
            <Typography.Paragraph>
              <pre style={{ fontSize: 12, whiteSpace: 'pre-wrap' }}>
                {JSON.stringify(detail.evidence, null, 2)}
              </pre>
            </Typography.Paragraph>
          </Space>
        ) : null}
      </Drawer>
    </div>
  )
}
