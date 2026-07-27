import { SendOutlined } from '@ant-design/icons'
import {
  Button,
  Form,
  Input,
  InputNumber,
  Select,
  Space,
  Table,
  Tag,
  Tree,
  Typography,
  message,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import type { DataNode } from 'antd/es/tree'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import type { LabelTaxonomyNode, ReviewAssignmentBatch, ReviewAssignmentReviewer } from '../api/types'
import { ContentCard } from '../components/ui'

function buildCheckableTree(nodes: LabelTaxonomyNode[]): DataNode[] {
  return nodes.map((group) => ({
    key: `level:${group.id}`,
    title: group.name,
    disableCheckbox: true,
    selectable: false,
    children: (group.children ?? []).map((leaf) => ({
      key: leaf.id,
      title: `${leaf.name} (${leaf.id})`,
      isLeaf: true,
    })),
  }))
}

function collectLeafKeys(checked: string[]): string[] {
  return checked.filter((k) => !k.startsWith('level:'))
}

export function ReviewAssignmentAdminPage() {
  const [taxonomy, setTaxonomy] = useState<LabelTaxonomyNode[]>([])
  const [reviewers, setReviewers] = useState<ReviewAssignmentReviewer[]>([])
  const [batches, setBatches] = useState<ReviewAssignmentBatch[]>([])
  const [loading, setLoading] = useState(false)
  const [previewCount, setPreviewCount] = useState<number | null>(null)
  const [checkedKeys, setCheckedKeys] = useState<string[]>([])
  const [form] = Form.useForm<{
    name: string
    queue_limit: number
    assignee_id?: string
  }>()

  const treeData = useMemo(() => buildCheckableTree(taxonomy), [taxonomy])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [tax, rev, batchRes] = await Promise.all([
        api.getLabelTaxonomy(),
        api.listReviewAssignmentReviewers(),
        api.listReviewAssignmentBatches(),
      ])
      setTaxonomy(tax)
      setReviewers(rev)
      setBatches(batchRes.items)
    } catch {
      message.error('加载任务数据失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const labelIds = useMemo(() => collectLeafKeys(checkedKeys), [checkedKeys])

  const handlePreview = async () => {
    const queueLimit = form.getFieldValue('queue_limit') ?? 50
    if (!labelIds.length) {
      message.warning('请至少选择一个标签')
      return
    }
    try {
      const res = await api.previewReviewAssignment({
        label_ids: labelIds,
        queue_limit: queueLimit,
      })
      setPreviewCount(res.count)
    } catch {
      message.error('预览失败')
    }
  }

  const handleDispatch = async () => {
    const values = await form.validateFields()
    if (!labelIds.length) {
      message.warning('请至少选择一个标签')
      return
    }
    try {
      await api.createReviewAssignmentBatch({
        name: values.name,
        label_ids: labelIds,
        queue_limit: values.queue_limit,
        assignee_id: values.assignee_id || null,
      })
      message.success('校核任务已派发')
      form.resetFields()
      setCheckedKeys([])
      setPreviewCount(null)
      await load()
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : '派发失败')
    }
  }

  const handleClose = async (batchId: string) => {
    try {
      await api.closeReviewAssignmentBatch(batchId)
      message.success('任务已关闭')
      await load()
    } catch {
      message.error('关闭失败')
    }
  }

  const columns: ColumnsType<ReviewAssignmentBatch> = [
    { title: '任务名称', dataIndex: 'name', width: 200 },
    {
      title: '标签范围',
      key: 'labels',
      render: (_, r) => (
        <Space size={4} wrap>
          {r.label_ids.map((id) => (
            <Tag key={id}>{id}</Tag>
          ))}
        </Space>
      ),
    },
    {
      title: '进度',
      key: 'progress',
      width: 160,
      render: (_, r) => (
        <Typography.Text type="secondary">
          完成 {r.item_done ?? 0} / {r.item_total ?? 0} · 待领 {r.item_pending ?? 0}
        </Typography.Text>
      ),
    },
    {
      title: '指定校核员',
      key: 'assignee',
      width: 120,
      render: (_, r) => {
        if (!r.assignee_id) return <Tag>开放领取</Tag>
        const rev = reviewers.find((x) => x.id === r.assignee_id)
        return rev?.display_name ?? r.assignee_id.slice(0, 8)
      },
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (v: string, r) => {
        const allDone =
          (r.item_total ?? 0) > 0 && (r.item_done ?? 0) >= (r.item_total ?? 0)
        if (allDone || v === 'closed') {
          return <Tag color="success">已完成</Tag>
        }
        return <Tag color="processing">进行中</Tag>
      },
    },
    {
      title: '操作',
      key: 'action',
      width: 90,
      render: (_, r) =>
        r.status === 'open' && (r.item_done ?? 0) < (r.item_total ?? 0) ? (
          <Button type="link" size="small" onClick={() => void handleClose(r.id)}>
            关闭
          </Button>
        ) : null,
    },
  ]

  return (
    <div data-testid="review-assignment-admin-page">
      <ContentCard title="新建派发任务">
        <Form
          form={form}
          layout="vertical"
          initialValues={{ queue_limit: 50 }}
          onValuesChange={() => setPreviewCount(null)}
        >
          <Form.Item name="name" label="任务名称" rules={[{ required: true, message: '请输入任务名称' }]}>
            <Input placeholder="例如：时段标签专项校核" maxLength={120} />
          </Form.Item>
          <Form.Item label="标签范围（可多选）" required>
            <Tree
              checkable
              selectable={false}
              treeData={treeData}
              checkedKeys={checkedKeys}
              onCheck={(keys) => {
                const list = Array.isArray(keys) ? keys : keys.checked
                setCheckedKeys(collectLeafKeys(list.map(String)))
              }}
              height={280}
              style={{ border: '1px solid var(--color-hairline)', borderRadius: 8, padding: 8 }}
            />
          </Form.Item>
          <Space wrap align="start">
            <Form.Item name="queue_limit" label="队列数量上限" rules={[{ required: true }]}>
              <InputNumber min={1} max={500} style={{ width: 140 }} />
            </Form.Item>
            <Form.Item name="assignee_id" label="指定校核员（可选）">
              <Select
                allowClear
                placeholder="不指定则开放领取"
                style={{ minWidth: 200 }}
                options={reviewers.map((r) => ({
                  value: r.id,
                  label: `${r.display_name} (${r.username})`,
                }))}
              />
            </Form.Item>
          </Space>
          <Space>
            <Button onClick={() => void handlePreview()} disabled={!labelIds.length}>
              预览可派发数量
            </Button>
            {previewCount != null ? (
              <Typography.Text type="secondary">当前可派发 {previewCount} 条</Typography.Text>
            ) : null}
            <Button type="primary" icon={<SendOutlined />} onClick={() => void handleDispatch()}>
              确认派发
            </Button>
          </Space>
        </Form>
      </ContentCard>

      <ContentCard title="已派发任务" noPadding>
        <Table
          rowKey="id"
          loading={loading}
          columns={columns}
          dataSource={batches}
          pagination={{ pageSize: 10 }}
        />
      </ContentCard>
    </div>
  )
}
