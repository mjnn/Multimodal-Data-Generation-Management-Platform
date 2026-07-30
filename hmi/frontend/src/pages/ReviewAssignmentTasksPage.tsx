import { PlayCircleOutlined } from '@ant-design/icons'
import { Button, Segmented, Space, Table, Tag, Typography, message } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import type { ReviewAssignmentBatch } from '../api/types'
import { ContentCard } from '../components/ui'

const BATCH_KIND_LABEL: Record<string, string> = {
  low_confidence: '低置信度任务',
  assigned: '分配给我的任务',
  public_pool: '任务池公开领取',
}

type TaskView = 'active' | 'completed' | 'all'

function resolveBatchKind(row: ReviewAssignmentBatch): string {
  if (row.batch_kind) return row.batch_kind
  if (row.assignee_id) return 'assigned'
  return 'public_pool'
}

export function ReviewAssignmentTasksPage() {
  const [batches, setBatches] = useState<ReviewAssignmentBatch[]>([])
  const [loading, setLoading] = useState(false)
  const [claimingId, setClaimingId] = useState<string | null>(null)
  const [view, setView] = useState<TaskView>('active')
  const navigate = useNavigate()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await api.listMyReviewAssignments({ view })
      setBatches(res.items)
    } catch {
      message.error('加载任务列表失败')
    } finally {
      setLoading(false)
    }
  }, [view])

  useEffect(() => {
    void load()
  }, [load])

  const myDoneTotal = useMemo(
    () => batches.reduce((sum, b) => sum + (b.my_done ?? 0), 0),
    [batches],
  )

  const handleClaim = async (batch: ReviewAssignmentBatch) => {
    const limit = batch.item_pending ?? batch.queue_limit
    if (!limit) {
      message.info('没有可领取的条目')
      return
    }
    setClaimingId(batch.id)
    try {
      const res = await api.claimReviewAssignment({ batch_id: batch.id, limit })
      message.success(`已领取 ${res.count} 条`)
      await load()
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : '领取失败')
    } finally {
      setClaimingId(null)
    }
  }

  const startReview = (batchId: string) => {
    navigate(`/review/workbench?batch=${encodeURIComponent(batchId)}`)
  }

  const columns: ColumnsType<ReviewAssignmentBatch> = [
    { title: '任务名称', dataIndex: 'name', width: 200 },
    {
      title: '任务类型',
      key: 'batch_kind',
      width: 160,
      render: (_, r) => {
        const kind = resolveBatchKind(r)
        return <Tag>{BATCH_KIND_LABEL[kind] ?? kind}</Tag>
      },
    },
    {
      title: '批次状态',
      key: 'batch_status',
      width: 100,
      render: (_, r) =>
        r.status === 'closed' ? <Tag color="default">已关闭</Tag> : <Tag color="processing">进行中</Tag>,
    },
    {
      title: '标签',
      key: 'labels',
      render: (_, r) => (
        <Space size={4} wrap>
          {r.label_ids.slice(0, 3).map((id) => (
            <Tag key={id}>{id}</Tag>
          ))}
          {r.label_ids.length > 3 ? <Tag>+{r.label_ids.length - 3}</Tag> : null}
        </Space>
      ),
    },
    {
      title: '我的进度',
      key: 'progress',
      width: 220,
      render: (_, r) => {
        const myPending = Math.max(0, (r.my_claimed ?? 0) - (r.my_done ?? 0))
        const staged = r.my_staged_count ?? 0
        return (
          <Typography.Text type="secondary">
            待审 {myPending}
            {staged > 0 ? ` · 已暂存 ${staged}` : ''}
            {' · '}
            已完成 {r.my_done ?? 0}
            {view !== 'completed' ? ` / 池内 ${r.item_total ?? 0}` : ''}
          </Typography.Text>
        )
      },
    },
    {
      title: '我的状态',
      key: 'my_status',
      width: 110,
      render: (_, r) => {
        const myPending = Math.max(0, (r.my_claimed ?? 0) - (r.my_done ?? 0))
        const myTotal = (r.my_claimed ?? 0) + (r.my_done ?? 0)
        if (myTotal > 0 && myPending === 0) {
          return <Tag color="success">我已完成</Tag>
        }
        if (myPending > 0) {
          return <Tag color="processing">进行中</Tag>
        }
        if ((r.item_pending ?? 0) > 0) {
          return <Tag>待领取</Tag>
        }
        return <Tag color="default">—</Tag>
      },
    },
    {
      title: '池内待领',
      dataIndex: 'item_pending',
      width: 100,
      render: (v: number | undefined) => v ?? 0,
    },
    {
      title: '操作',
      key: 'action',
      width: 220,
      render: (_, r) => {
        const myPending = Math.max(0, (r.my_claimed ?? 0) - (r.my_done ?? 0))
        const hasStaged = (r.my_staged_count ?? 0) > 0
        const canClaim =
          resolveBatchKind(r) === 'public_pool' && r.status === 'open' && (r.item_pending ?? 0) > 0
        const canStart = myPending > 0 || hasStaged
        return (
          <Space>
            {canClaim ? (
              <Button
                size="small"
                loading={claimingId === r.id}
                onClick={() => void handleClaim(r)}
              >
                领取任务
              </Button>
            ) : null}
            {canStart ? (
              <Button
                type="primary"
                size="small"
                icon={<PlayCircleOutlined />}
                onClick={() => startReview(r.id)}
              >
                开始校核
              </Button>
            ) : null}
          </Space>
        )
      },
    },
  ]

  const emptyText =
    view === 'completed'
      ? '暂无已完成的校核任务（完成条目后会出现在这里）'
      : view === 'active'
        ? '暂无进行中的校核任务'
        : '暂无可领取的校核任务'

  return (
    <div data-testid="review-assignment-tasks-page">
      <ContentCard title="任务领取" noPadding>
        <div style={{ padding: '12px 16px 0' }}>
          <Space wrap style={{ marginBottom: 12, width: '100%', justifyContent: 'space-between' }}>
            <Segmented
              value={view}
              onChange={(v) => setView(v as TaskView)}
              options={[
                { label: '进行中', value: 'active' },
                { label: '已完成', value: 'completed' },
                { label: '全部', value: 'all' },
              ]}
            />
            {view === 'completed' || view === 'all' ? (
              <Typography.Text type="secondary">
                本页我的累计完成 <strong>{myDoneTotal}</strong> 条
              </Typography.Text>
            ) : null}
          </Space>
        </div>
        <Table
          rowKey="id"
          loading={loading}
          columns={columns}
          dataSource={batches}
          locale={{ emptyText }}
          pagination={{ pageSize: 10 }}
        />
      </ContentCard>
    </div>
  )
}
