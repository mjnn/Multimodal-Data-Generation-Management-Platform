import { SearchOutlined } from '@ant-design/icons'
import { Alert, Button, Input, Space, Typography, message } from 'antd'
import { useEffect, useState } from 'react'
import { api } from '../api'
import type { TaxonomyNodeDetail } from '../api/types'
import { DatasetLabelFilterForm, type LabelFilters } from './DatasetLabelFilterForm'
import { ContentCard } from './ui'

export type OverviewQueryHit = {
  clip_id: string
  run_id: string
  score: number
  match_mode: string
  scene_description?: string
  label_preview?: string
}

type Props = {
  onApplied: (result: {
    active: boolean
    clipIds: string[] | null
    hits: OverviewQueryHit[]
    semanticMode: string
    embeddingUsed: boolean
    message?: string | null
  }) => void
}

export function OverviewClipSearchPanel({ onApplied }: Props) {
  const [nodes, setNodes] = useState<TaxonomyNodeDetail[]>([])
  const [labelFilters, setLabelFilters] = useState<LabelFilters>({})
  const [semanticQuery, setSemanticQuery] = useState('')
  const [loading, setLoading] = useState(false)
  const [hint, setHint] = useState<string | null>(null)
  const [taxError, setTaxError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const ctx = await api.getTaxonomyContext()
        const publishedId = ctx.published_taxonomy_version_id
        if (!publishedId) {
          if (!cancelled) {
            setNodes([])
            setTaxError('暂无已发布标签树，标签检索不可用；仍可使用场景描述语义检索。')
          }
          return
        }
        const tree = await api.getTaxonomyTree(publishedId)
        if (!cancelled) {
          setNodes(tree.nodes)
          setTaxError(null)
        }
      } catch (e: unknown) {
        if (!cancelled) {
          setTaxError(e instanceof Error ? e.message : '加载标签树失败')
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const hasFilters = Object.keys(labelFilters).length > 0
  const hasSemantic = semanticQuery.trim().length > 0

  const applySearch = async () => {
    if (!hasFilters && !hasSemantic) {
      message.warning('请至少设置标签筛选或输入场景描述检索语句')
      return
    }
    setLoading(true)
    setHint(null)
    try {
      const res = await api.queryOverviewClips({
        labelFilters: hasFilters ? labelFilters : undefined,
        semanticQuery: hasSemantic ? semanticQuery.trim() : undefined,
      })
      const hits = (res.items ?? []) as OverviewQueryHit[]
      const clipIds = hits.map((h) => h.clip_id)
      onApplied({
        active: true,
        clipIds,
        hits,
        semanticMode: res.semantic_mode,
        embeddingUsed: res.embedding_used,
        message: res.message,
      })
      if (hits.length === 0) {
        setHint(res.message || '未匹配到相关 Clip（0 条）')
      } else if (res.embedding_used) {
        setHint(`已匹配 ${hits.length} 条（场景/标签文本向量 + 文本相关度）`)
      } else if (hasSemantic) {
        setHint(`已匹配 ${hits.length} 条（场景/标签文本相关度；配置 DASHSCOPE_API_KEY 可启用文本向量）`)
      } else {
        setHint(`已匹配 ${hits.length} 条（按标签筛选）`)
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '检索失败'
      message.error(msg)
      setHint(msg)
    } finally {
      setLoading(false)
    }
  }

  const clearSearch = () => {
    setLabelFilters({})
    setSemanticQuery('')
    setHint(null)
    onApplied({
      active: false,
      clipIds: null,
      hits: [],
      semanticMode: 'none',
      embeddingUsed: false,
      message: null,
    })
  }

  return (
    <ContentCard title="数据检索">
      <div data-testid="overview-clip-search">
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        <div>
          <Typography.Text strong style={{ display: 'block', marginBottom: 8 }}>
            标签检索
          </Typography.Text>
          {taxError ? (
            <Alert type="info" showIcon message={taxError} style={{ marginBottom: 8 }} />
          ) : null}
          <DatasetLabelFilterForm nodes={nodes} value={labelFilters} onChange={setLabelFilters} />
        </div>

        <div>
          <Typography.Text strong style={{ display: 'block', marginBottom: 8 }}>
            场景描述语义检索
          </Typography.Text>
          <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginTop: 0 }}>
            用自然语言描述场景（如「夜间后排儿童」）。匹配对象是场景描述与标签文本：文本相关度 ≥
            0.25，或（配置 DASHSCOPE_API_KEY 后）查询文本向量与场景/标签文本向量的余弦 ≥ 0.40；并在最佳匹配附近做相对截断。不使用
            Clip 多模态 fusion 向量。标签筛选与场景检索为 AND。
          </Typography.Paragraph>
          <Input.TextArea
            rows={2}
            allowClear
            placeholder="输入场景描述检索语句"
            value={semanticQuery}
            onChange={(e) => setSemanticQuery(e.target.value)}
            onPressEnter={(e) => {
              if (!e.shiftKey) {
                e.preventDefault()
                void applySearch()
              }
            }}
          />
        </div>

        <Space wrap>
          <Button type="primary" icon={<SearchOutlined />} loading={loading} onClick={() => void applySearch()}>
            检索
          </Button>
          <Button onClick={clearSearch} disabled={loading}>
            清除检索
          </Button>
        </Space>

        {hint ? (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {hint}
          </Typography.Text>
        ) : null}
      </Space>
      </div>
    </ContentCard>
  )
}
