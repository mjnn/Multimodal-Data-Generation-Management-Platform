import {
  CheckCircleOutlined,
  PlayCircleOutlined,
  SearchOutlined,
  WarningOutlined,
} from '@ant-design/icons'
import {
  Alert,
  AutoComplete,
  Button,
  Checkbox,
  Empty,
  Input,
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
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import { clipDisplayName } from '../utils/clipDisplay'
import type {
  LabelTaxonomyNode,
  ReviewTaskCandidate,
  ReviewTaskScope,
  TaxonomyNodeDetail,
} from '../api/types'
import { ContentCard, PageHeader, PageStack } from '../components/ui'
import { useReviewTaskQueryState } from '../hooks/useListQueryState'
import { schemaEnumValues } from '../utils/labelDisplay'

const SCOPE_LABEL: Record<ReviewTaskScope, string> = {
  unreviewed: '未校核',
  pending_review: '待校核',
  reviewed: '已校核',
  all: '全部',
}

const STATUS_COLOR = {
  pending_review: 'orange',
  reviewed: 'success',
} as const

function taxonomyNodesToSidebarTree(nodes: TaxonomyNodeDetail[]): LabelTaxonomyNode[] {
  const groups = new Map<string, LabelTaxonomyNode>()
  for (const n of nodes) {
    if (n.is_active === false) continue
    const code = n.level_code || 'other'
    if (!groups.has(code)) {
      groups.set(code, { id: code, name: n.level_name || code, children: [] })
    }
    groups.get(code)!.children!.push({ id: n.label_id, name: n.name })
  }
  return [...groups.values()].sort((a, b) => a.id.localeCompare(b.id))
}

function toTreeData(nodes: LabelTaxonomyNode[]): DataNode[] {
  return nodes.map((n) => ({
    key: n.id,
    title: n.name,
    children: n.children ? toTreeData(n.children) : undefined,
    selectable: !n.children?.length,
  }))
}

function findLabelTitle(tree: LabelTaxonomyNode[], labelId: string): string {
  for (const node of tree) {
    if (node.id === labelId) return node.name
    if (node.children) {
      const child = node.children.find((c) => c.id === labelId)
      if (child) return child.name
    }
  }
  return labelId
}

export function ReviewQueuePage() {
  const navigate = useNavigate()
  const {
    taskFilters,
    selectedLabelId,
    filterValue,
    taskScope,
    page,
    setSelectedLabelId,
    clearLabel,
    applySearchTask,
    setTaskScope,
    setDisputesOnly,
    setPage,
    buildReviewHref,
    hasTask,
    disputesOnly,
  } = useReviewTaskQueryState()

  const [inputValue, setInputValue] = useState(filterValue)
  const [suggestions, setSuggestions] = useState<string[]>([])
  const [taxonomyNodes, setTaxonomyNodes] = useState<TaxonomyNodeDetail[]>([])
  const [loading, setLoading] = useState(false)
  const [items, setItems] = useState<ReviewTaskCandidate[]>([])
  const [total, setTotal] = useState(0)
  const pageSize = 20

  useEffect(() => {
    setInputValue(filterValue)
  }, [filterValue])

  useEffect(() => {
    void api.getLabelSuggestions().then(setSuggestions).catch(() => setSuggestions([]))
    void (async () => {
      try {
        const versions = await api.listTaxonomyVersions()
        const published = versions.find((v) => v.status === 'published')
        if (published) {
          const tree = await api.getTaxonomyTree(published.id)
          setTaxonomyNodes(tree.nodes.filter((n) => n.is_active !== false))
        } else {
          setTaxonomyNodes([])
        }
      } catch {
        setTaxonomyNodes([])
      }
    })()
  }, [])

  const taxonomy = useMemo(() => taxonomyNodesToSidebarTree(taxonomyNodes), [taxonomyNodes])
  const treeData = useMemo(() => toTreeData(taxonomy), [taxonomy])
  const nodeById = useMemo(
    () => new Map(taxonomyNodes.map((n) => [n.label_id, n])),
    [taxonomyNodes],
  )
  const selectedNode = selectedLabelId ? nodeById.get(selectedLabelId) : undefined
  const enumValues = useMemo(() => schemaEnumValues(selectedNode), [selectedNode])

  const loadTask = useCallback(async () => {
    const active = Object.fromEntries(
      Object.entries(taskFilters).filter(([, v]) => v !== '' && v != null),
    )
    if (Object.keys(active).length === 0) {
      setItems([])
      setTotal(0)
      return
    }
    setLoading(true)
    try {
      const res = await api.getReviewCandidates({
        labelFilters: active,
        reviewScope: taskScope,
        disputesOnly,
        limit: pageSize,
        offset: (page - 1) * pageSize,
      })
      setItems(res.items)
      setTotal(res.total)
    } catch {
      message.error('加载校核任务失败')
    } finally {
      setLoading(false)
    }
  }, [disputesOnly, page, taskFilters, taskScope])

  useEffect(() => {
    void loadTask()
  }, [loadTask])

  const submitSearch = (raw?: string) => {
    const value = (raw ?? inputValue).trim()
    setInputValue(value)
    if (!selectedLabelId) {
      message.warning('请先在左侧标签树选择要打标的标签节点')
      return
    }
    if (!value) {
      message.warning('请输入或选择标签取值')
      return
    }
    applySearchTask(selectedLabelId, value)
  }

  const openReview = useCallback(
    (row: ReviewTaskCandidate) => {
      navigate(buildReviewHref(row.clip_id, row.run_id))
    },
    [buildReviewHref, navigate],
  )

  const startFirst = () => {
    if (items.length === 0) {
      message.info('当前任务没有可校核的 Clip')
      return
    }
    openReview(items[0])
  }

  const columns: ColumnsType<ReviewTaskCandidate> = useMemo(
    () => [
      {
        title: 'Clip',
        key: 'clip',
        render: (_, row) => (
          <Space direction="vertical" size={2}>
            <Typography.Text strong className="mono">
              {clipDisplayName(row)}
            </Typography.Text>
            <Typography.Text type="secondary" className="mono" style={{ fontSize: 11 }}>
              {row.clip_id}
            </Typography.Text>
          </Space>
        ),
      },
      {
        title: 'AI 标签',
        dataIndex: 'label_preview',
        render: (v: string) => v || '—',
      },
      {
        title: '不一致标签',
        key: 'disputes',
        width: 140,
        render: (_, row) =>
          (row.dispute_count ?? 0) > 0 ? (
            <Tag color="warning" icon={<WarningOutlined />}>
              {row.dispute_count} 项不一致
            </Tag>
          ) : (
            <Tag color="success">一致</Tag>
          ),
      },
      {
        title: '校核状态',
        key: 'review_status',
        width: 120,
        render: (_, row) =>
          row.review_status === 'reviewed' ? (
            <Tag color={STATUS_COLOR.reviewed}>已校核</Tag>
          ) : (
            <Tag color={STATUS_COLOR.pending_review}>待校核</Tag>
          ),
      },
      {
        title: '操作',
        key: 'action',
        width: 100,
        render: (_, row) => (
          <Button type="link" onClick={() => openReview(row)}>
            校核
          </Button>
        ),
      },
    ],
    [openReview],
  )

  const taskLabelTitle = selectedLabelId ? findLabelTitle(taxonomy, selectedLabelId) : null
  const activeEntry = Object.entries(taskFilters)[0]

  return (
    <PageStack data-testid="review-queue-page">
      <PageHeader
        title="标签校核任务"
        description="左侧选标签树节点，右侧输入取值（如 morning）加载任务；在结果中找出误标 Clip。"
        icon={<CheckCircleOutlined />}
        extra={
          hasTask ? (
            <Button
              type="primary"
              icon={<PlayCircleOutlined />}
              onClick={startFirst}
              disabled={items.length === 0}
            >
              开始校核
            </Button>
          ) : undefined
        }
      />

      <div className="search-layout">
        <aside className="search-layout__aside" aria-label="标签树筛选">
          <ContentCard title="OMS 标签树">
            <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 12 }}>
              选择要打标维度（如「时段」），再在右侧输入取值
            </Typography.Paragraph>
            <Tree
              treeData={treeData}
              selectedKeys={selectedLabelId ? [selectedLabelId] : []}
              onSelect={(keys) => {
                const id = keys[0] as string | undefined
                if (id) setSelectedLabelId(id)
              }}
              defaultExpandAll
              style={{ maxHeight: 520, overflow: 'auto' }}
            />
          </ContentCard>
        </aside>

        <div className="search-layout__main">
          <Space direction="vertical" size={16} style={{ width: '100%' }}>
            <ContentCard title="任务检索">
              <Space direction="vertical" size={12} style={{ width: '100%' }}>
                {selectedLabelId ? (
                  <Tag closable onClose={clearLabel}>
                    标签: {taskLabelTitle ?? selectedLabelId}
                    <Typography.Text type="secondary" className="mono" style={{ marginLeft: 6, fontSize: 11 }}>
                      {selectedLabelId}
                    </Typography.Text>
                  </Tag>
                ) : (
                  <Alert type="info" showIcon message="请先在左侧选择标签节点" style={{ padding: '8px 12px' }} />
                )}

                {selectedNode?.dtype === 'bool' ? (
                  <Select
                    allowClear
                    placeholder="选择取值"
                    style={{ width: '100%' }}
                    value={inputValue || undefined}
                    options={[
                      { value: 'true', label: '是' },
                      { value: 'false', label: '否' },
                    ]}
                    onChange={(v) => {
                      if (!selectedLabelId || !v) return
                      setInputValue(v)
                      applySearchTask(selectedLabelId, v === 'true')
                    }}
                  />
                ) : enumValues.length > 0 ? (
                  <Select
                    allowClear
                    showSearch
                    placeholder={`选择 ${taskLabelTitle ?? '标签'} 取值`}
                    style={{ width: '100%' }}
                    value={inputValue || undefined}
                    options={enumValues.map((v) => ({ value: v, label: v }))}
                    onChange={(v) => {
                      const next = v ?? ''
                      setInputValue(next)
                      if (selectedLabelId && next) applySearchTask(selectedLabelId, next)
                    }}
                  />
                ) : (
                  <AutoComplete
                    options={suggestions.map((s) => ({ value: s }))}
                    style={{ width: '100%' }}
                    value={inputValue}
                    onChange={setInputValue}
                    onSelect={(v) => {
                      setInputValue(v)
                      submitSearch(v)
                    }}
                  >
                    <Input.Search
                      size="large"
                      placeholder={
                        selectedLabelId
                          ? `输入 ${taskLabelTitle ?? '标签'} 取值，如 morning`
                          : '请先选择左侧标签'
                      }
                      enterButton={<SearchOutlined />}
                      loading={loading}
                      disabled={!selectedLabelId}
                      onSearch={submitSearch}
                      aria-label="校核任务标签取值"
                    />
                  </AutoComplete>
                )}

                {!hasTask && selectedLabelId && enumValues.length > 0 && (
                  <Space wrap>
                    {enumValues.slice(0, 8).map((s) => (
                      <Tag
                        key={s}
                        style={{ cursor: 'pointer' }}
                        onClick={() => {
                          setInputValue(s)
                          applySearchTask(selectedLabelId, s)
                        }}
                      >
                        {s}
                      </Tag>
                    ))}
                  </Space>
                )}

                <Space wrap align="center">
                  <Typography.Text type="secondary">校核范围</Typography.Text>
                  <Select
                    style={{ minWidth: 180 }}
                    value={taskScope}
                    options={(Object.keys(SCOPE_LABEL) as ReviewTaskScope[]).map((v) => ({
                      value: v,
                      label: SCOPE_LABEL[v],
                    }))}
                    onChange={setTaskScope}
                  />
                  <Checkbox
                    checked={disputesOnly}
                    onChange={(e) => setDisputesOnly(e.target.checked)}
                  >
                    仅看不一致
                  </Checkbox>
                </Space>
              </Space>
            </ContentCard>

            {!hasTask ? (
              <ContentCard>
                <Empty
                  description={
                    selectedLabelId
                      ? '选择或输入标签取值以加载校核任务'
                      : '选择标签树节点并输入取值'
                  }
                />
              </ContentCard>
            ) : (
              <ContentCard
                title="任务结果"
                extra={
                  activeEntry ? (
                    <Typography.Text type="secondary">
                      {findLabelTitle(taxonomy, activeEntry[0])} = {String(activeEntry[1])} · 共{' '}
                      {total} 条
                    </Typography.Text>
                  ) : (
                    <Typography.Text type="secondary">共 {total} 条</Typography.Text>
                  )
                }
                noPadding
              >
                <Table
                  rowKey={(r) => `${r.clip_id}|${r.run_id}`}
                  loading={loading}
                  columns={columns}
                  dataSource={items}
                  locale={{ emptyText: '无匹配 Clip，请调整标签或校核范围' }}
                  rowClassName={() => 'clickable-row'}
                  onRow={(row) => ({ onClick: () => openReview(row) })}
                  pagination={{
                    current: page,
                    pageSize,
                    total,
                    showSizeChanger: false,
                    onChange: setPage,
                  }}
                />
              </ContentCard>
            )}
          </Space>
        </div>
      </div>
    </PageStack>
  )
}
