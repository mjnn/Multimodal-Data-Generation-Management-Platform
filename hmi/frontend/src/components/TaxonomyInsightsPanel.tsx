import { Button, Drawer, Input, Progress, Select, Space, Table, Tag, Tooltip, Typography, message } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import type { TaxonomyCoverageItem, TaxonomyVersion } from '../api/types'
import { FilterBar } from './ui'
import { formatTaxonomyVersionLabel } from '../utils/taxonomyDisplay'

type CoverageFilter = 'all' | 'gap' | 'empty' | 'covered'

export function TaxonomyInsightsPanel() {
  const [versions, setVersions] = useState<TaxonomyVersion[]>([])
  const [versionId, setVersionId] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [items, setItems] = useState<TaxonomyCoverageItem[]>([])
  const [summary, setSummary] = useState<{ review_pool_count?: number; gap_node_count?: number }>({})
  const [tablePage, setTablePage] = useState(1)
  const [tablePageSize, setTablePageSize] = useState(15)
  const [coverageFilter, setCoverageFilter] = useState<CoverageFilter>('all')
  const [keyword, setKeyword] = useState('')
  const [usageLabelId, setUsageLabelId] = useState<string | null>(null)
  const [usageDetail, setUsageDetail] = useState<{
    clip_with_label_count: number
    clip_samples: Array<{ clip_id: string; run_id: string; value: string }>
    dataset_reference_count: number
  } | null>(null)

  useEffect(() => {
    void api.listTaxonomyVersions().then((v) => {
      setVersions(v)
      const published = v.find((x) => x.status === 'published')
      if (published) setVersionId(published.id)
      else if (v[0]) setVersionId(v[0].id)
    })
  }, [])

  const loadCoverage = useCallback(async (vid: string) => {
    setLoading(true)
    try {
      const res = await api.getTaxonomyCoverage(vid)
      setItems(res.items)
      setSummary({
        review_pool_count: res.review_pool_count,
        gap_node_count: res.gap_node_count,
      })
    } catch {
      message.error('加载覆盖率失败')
      setItems([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (versionId) void loadCoverage(versionId)
    setTablePage(1)
    setCoverageFilter('all')
    setKeyword('')
  }, [versionId, loadCoverage])

  useEffect(() => {
    setTablePage(1)
  }, [coverageFilter, keyword])

  const filterCounts = useMemo(
    () => ({
      all: items.length,
      gap: items.filter((row) => row.has_gap).length,
      empty: items.filter((row) => row.reviewed_with_label === 0).length,
      covered: items.filter((row) => row.reviewed_with_label > 0).length,
    }),
    [items],
  )

  const filteredItems = useMemo(() => {
    const q = keyword.trim().toLowerCase()
    let list = items
    if (q) {
      list = list.filter(
        (row) =>
          row.label_id.toLowerCase().includes(q) ||
          (row.name ?? '').toLowerCase().includes(q),
      )
    }
    switch (coverageFilter) {
      case 'gap':
        return list.filter((row) => row.has_gap)
      case 'empty':
        return list.filter((row) => row.reviewed_with_label === 0)
      case 'covered':
        return list.filter((row) => row.reviewed_with_label > 0)
      default:
        return list
    }
  }, [items, coverageFilter, keyword])

  const openUsage = useCallback(async (labelId: string) => {
    if (!versionId) return
    setUsageLabelId(labelId)
    try {
      const u = await api.getTaxonomyNodeUsage(labelId, versionId)
      setUsageDetail(u)
    } catch {
      message.error('加载节点引用失败')
      setUsageDetail(null)
    }
  }, [versionId])

  const columns: ColumnsType<TaxonomyCoverageItem> = useMemo(
    () => [
      {
        title: '标签',
        key: 'name',
        render: (_, row) => (
          <Space direction="vertical" size={0}>
            <Typography.Text>{row.name ?? row.label_id}</Typography.Text>
            <Typography.Text type="secondary" className="mono" style={{ fontSize: 11 }}>
              {row.label_id}
            </Typography.Text>
          </Space>
        ),
      },
      {
        title: (
          <Tooltip title="绑定该标签树版本的校核池 clip 中，此标签有非空 AI/校核值的条数">
            有值 clip
          </Tooltip>
        ),
        dataIndex: 'reviewed_with_label',
        width: 96,
      },
      {
        title: (
          <Tooltip title="校核池 clip 中，此标签未出现或值为空的条数（= 校核池总数 − 有值 clip）">
            无值 clip
          </Tooltip>
        ),
        dataIndex: 'reviewed_missing_label',
        width: 96,
      },
      {
        title: (
          <Tooltip title="枚举型标签：各取值在校核池中的 clip 数量；若某枚举取值从未出现则标记「枚举缺口」">
            取值分布
          </Tooltip>
        ),
        key: 'dist',
        render: (_, row) => {
          const total = Object.values(row.value_counts).reduce((a, b) => a + b, 0)
          const max = Math.max(1, ...Object.values(row.value_counts), 1)
          if (row.enum_values.length === 0) {
            return total > 0 ? `${total} clip` : <Tag>无数据</Tag>
          }
          return (
            <Space direction="vertical" size={4} style={{ width: '100%' }}>
              {row.enum_values.slice(0, 4).map((ev) => {
                const c = row.value_counts[ev] ?? 0
                return (
                  <Space key={ev} size={8} style={{ width: '100%' }}>
                    <Typography.Text style={{ width: 72, fontSize: 11 }} ellipsis>
                      {ev}
                    </Typography.Text>
                    <Progress
                      percent={Math.round((c / max) * 100)}
                      size="small"
                      showInfo={false}
                      style={{ flex: 1, minWidth: 80 }}
                    />
                    <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                      {c}
                    </Typography.Text>
                  </Space>
                )
              })}
              {row.has_gap ? (
                <Tag color="warning">
                  {row.missing_enum_values.length > 0 ? '枚举缺口' : '无覆盖'}
                </Tag>
              ) : null}
            </Space>
          )
        },
      },
      {
        title: '',
        key: 'usage',
        width: 72,
        render: (_, row) => (
          <Button type="link" size="small" onClick={() => void openUsage(row.label_id)}>
            引用
          </Button>
        ),
      },
    ],
    [openUsage],
  )

  return (
    <div data-testid="taxonomy-insights-panel">
      <Typography.Paragraph type="secondary" style={{ marginBottom: 12, fontSize: 12 }}>
        统计绑定该标签树版本、且已入库校核记录的 clip（校核池）。每个标签看：有多少 clip 填了值、多少 clip
        未填；枚举型标签还看各取值是否都有样本。与数据总览里单 clip 的校核进度不是同一口径；校核池为空时各列均为 0。
      </Typography.Paragraph>
      <Space style={{ marginBottom: 12 }} wrap>
        <Typography.Text type="secondary">标签树版本</Typography.Text>
        <Select
          style={{ minWidth: 220 }}
          value={versionId ?? undefined}
          onChange={setVersionId}
          options={versions.map((v) => ({
            value: v.id,
            label: formatTaxonomyVersionLabel(v),
          }))}
        />
        {summary.review_pool_count != null ? (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            校核池 {summary.review_pool_count} clip
            {summary.review_pool_count === 0 ? '（暂无校核记录，覆盖率暂无意义）' : null}
            {' · '}
            需关注 {summary.gap_node_count ?? 0} 个标签
          </Typography.Text>
        ) : null}
      </Space>
      <Space direction="vertical" size={12} style={{ width: '100%', marginBottom: 12 }}>
        <FilterBar
          aria-label="标签覆盖率筛选"
          value={coverageFilter}
          onChange={(v) => setCoverageFilter(v as CoverageFilter)}
          total={filteredItems.length}
          totalLabel="条标签"
          options={[
            { value: 'all', label: '全部', count: filterCounts.all },
            { value: 'gap', label: '需关注', count: filterCounts.gap },
            { value: 'empty', label: '校核池无覆盖', count: filterCounts.empty },
            { value: 'covered', label: '校核池有覆盖', count: filterCounts.covered },
          ]}
        />
        <Input.Search
          allowClear
          placeholder="搜索标签名或 label_id"
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          style={{ maxWidth: 320 }}
          data-testid="taxonomy-coverage-search"
        />
      </Space>
      <Table
        rowKey="label_id"
        size="small"
        loading={loading}
        columns={columns}
        dataSource={filteredItems}
        pagination={{
          current: tablePage,
          pageSize: tablePageSize,
          showSizeChanger: true,
          pageSizeOptions: [10, 15, 20, 50],
          showTotal: (total) => `共 ${total} 条`,
          onChange: (page, pageSize) => {
            setTablePage(page)
            setTablePageSize(pageSize)
          },
        }}
      />
      <Drawer
        title={usageLabelId ? `节点引用 · ${usageLabelId}` : '节点引用'}
        open={Boolean(usageLabelId)}
        onClose={() => {
          setUsageLabelId(null)
          setUsageDetail(null)
        }}
        width={480}
      >
        {usageDetail ? (
          <Space direction="vertical" style={{ width: '100%' }}>
            <Typography.Text>校核 clip 有值: {usageDetail.clip_with_label_count}</Typography.Text>
            <Typography.Text type="secondary">
              数据集 filter 引用: {usageDetail.dataset_reference_count}
            </Typography.Text>
            {usageDetail.clip_samples.map((s) => (
              <div key={`${s.clip_id}:${s.run_id}`}>
                <Link to={`/clips/${encodeURIComponent(s.clip_id)}`}>
                  {s.clip_id.slice(0, 24)}…
                </Link>
                <Typography.Text type="secondary"> = {s.value}</Typography.Text>
              </div>
            ))}
          </Space>
        ) : null}
      </Drawer>
    </div>
  )
}
