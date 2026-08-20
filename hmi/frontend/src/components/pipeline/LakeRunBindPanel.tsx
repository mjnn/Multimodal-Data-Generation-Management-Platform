import { PlayCircleOutlined } from '@ant-design/icons'
import { Alert, Button, Checkbox, Select, Space, Table, Tag, Typography, message } from 'antd'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../../api'
import type { DataTypeRecipe, PlatformRunPreflight, PlatformSourceRecord } from '../../api/types'
import { rememberDataTypeId } from '../../context/DataTypeWorkspaceContext'
import { apiErrorMessage } from '../../utils/apiError'

type LakeKind = 'rosbag' | 'video' | 'audio' | 'text' | 'image'

function kindLabel(kind: string): string {
  switch (kind) {
    case 'rosbag':
      return 'Rosbag'
    case 'video':
      return '视频'
    case 'audio':
      return '音频'
    case 'text':
      return '文本'
    case 'image':
      return '图片'
    default:
      return kind
  }
}

function mergeSources(prev: PlatformSourceRecord[], next: PlatformSourceRecord[]): PlatformSourceRecord[] {
  const byId = new Map<string, PlatformSourceRecord>()
  for (const item of [...next, ...prev]) {
    byId.set(item.source_id, item)
  }
  return Array.from(byId.values()).sort((a, b) =>
    String(b.created_at || '').localeCompare(String(a.created_at || '')),
  )
}

function collectionKey(row: PlatformSourceRecord): string {
  return String(row.collection_id || row.source_id)
}

type LakeRunBindPanelProps = {
  initialDataTypeId?: string
  onDataTypeIdChange?: (id: string) => void
}

/** 管线管理 · 源湖开跑：选类型 → 筛合格源 → 多选 → 预检 → 自动 Sample+Run */
export function LakeRunBindPanel({ initialDataTypeId, onDataTypeIdChange }: LakeRunBindPanelProps) {
  const navigate = useNavigate()
  const [sources, setSources] = useState<PlatformSourceRecord[]>([])
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [dataTypes, setDataTypes] = useState<DataTypeRecipe[]>([])
  const [dataTypeId, setDataTypeId] = useState<string | undefined>(initialDataTypeId)
  const [preflight, setPreflight] = useState<PlatformRunPreflight | null>(null)
  const [loadingSources, setLoadingSources] = useState(false)
  const [running, setRunning] = useState(false)

  const selectedSources = useMemo(
    () => sources.filter((item) => selectedIds.includes(item.source_id)),
    [sources, selectedIds],
  )

  const selectedRecipe = useMemo(
    () => dataTypes.find((item) => item.id === dataTypeId) ?? null,
    [dataTypes, dataTypeId],
  )

  const displaySources = useMemo(() => {
    if (!dataTypeId || !selectedRecipe) return sources
    const kinds = new Set<string>()
    for (const slot of selectedRecipe.slots || []) {
      for (const k of slot.kinds || []) kinds.add(k)
    }
    for (const group of selectedRecipe.require_any_kinds || []) {
      for (const k of group) kinds.add(k)
    }
    if (!kinds.size) return sources
    return sources.filter((s) => kinds.has(s.kind))
  }, [sources, dataTypeId, selectedRecipe])

  const loadDataTypes = async () => {
    const res = await api.listDataTypes()
    setDataTypes((res.items || []).filter((item) => item.status === 'published'))
  }

  const loadSources = async (eligibleFor?: string) => {
    setLoadingSources(true)
    try {
      const res = await api.listPlatformSources(200, {
        eligibleFor: eligibleFor || undefined,
      })
      setSources((prev) => mergeSources(prev, res.items || []))
    } catch (e: unknown) {
      message.error(apiErrorMessage(e, '加载已入库源失败'))
    } finally {
      setLoadingSources(false)
    }
  }

  useEffect(() => {
    void loadSources()
    void loadDataTypes()
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mount once
  }, [])

  useEffect(() => {
    if (initialDataTypeId && !dataTypeId) setDataTypeId(initialDataTypeId)
  }, [initialDataTypeId, dataTypeId])

  useEffect(() => {
    if (!dataTypeId) return
    void loadSources(dataTypeId)
    setPreflight(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dataTypeId])

  const onSelectDataType = (value: string) => {
    setDataTypeId(value)
    onDataTypeIdChange?.(value)
    rememberDataTypeId(value)
  }

  const runPreflight = async () => {
    if (!dataTypeId || !selectedIds.length) return
    try {
      const result = await api.preflightPlatformRun({
        data_type_id: dataTypeId,
        source_ids: selectedIds,
      })
      setPreflight(result)
      if (result.ok) message.success('预检通过')
      else message.error('预检失败')
    } catch (e: unknown) {
      setPreflight(null)
      message.error(apiErrorMessage(e, '预检失败'))
    }
  }

  const createRun = async () => {
    if (!dataTypeId || !selectedIds.length || !preflight?.ok || running) return
    setRunning(true)
    try {
      const created = await api.createPlatformRun({
        data_type_id: dataTypeId,
        source_ids: selectedIds,
      })
      rememberDataTypeId(dataTypeId)
      message.success(`已创建平台运行：${created.run_id}（自动绑定 Sample ${created.sample_id}）`)
      void navigate(`/pipeline?tab=queue&run_id=${encodeURIComponent(created.run_id)}`)
    } catch (e: unknown) {
      message.error(apiErrorMessage(e, '创建运行失败'))
    } finally {
      setRunning(false)
    }
  }

  const toggleSelected = (sourceId: string, checked: boolean) => {
    setSelectedIds((prev) => {
      if (checked) return prev.includes(sourceId) ? prev : [...prev, sourceId]
      return prev.filter((id) => id !== sourceId)
    })
    setPreflight(null)
  }

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }} data-testid="lake-run-bind-panel">
      <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
        选择 published 数据类型后列出合格源（仍按采集批展示，不自动绑定）。勾选后预检并通过则创建运行；Sample
        由系统自动生成。入湖请前往「源湖入库」。
      </Typography.Paragraph>

      <Select
        data-testid="lake-run-data-type-select"
        placeholder="选择 published 数据类型"
        style={{ width: '100%', maxWidth: 480 }}
        value={dataTypeId}
        options={dataTypes.map((item) => ({
          value: item.id,
          label: `${item.title}（${item.id}）`,
        }))}
        onChange={onSelectDataType}
      />
      {selectedRecipe ? (
        <Typography.Text type="secondary">
          {selectedRecipe.purpose}
          {selectedRecipe.slots?.length
            ? ` · 槽位：${selectedRecipe.slots.map((s) => s.id).join(', ')}`
            : ''}
        </Typography.Text>
      ) : null}

      <div data-testid="lake-run-sources-table">
        <Space style={{ marginBottom: 8 }}>
          <Button size="small" loading={loadingSources} onClick={() => void loadSources(dataTypeId)}>
            刷新
          </Button>
          <Typography.Text type="secondary">
            已选 {selectedIds.length} 个
            {dataTypeId ? '（已按类型过滤）' : '（未选类型时显示全部；请先选类型再开跑）'}
          </Typography.Text>
        </Space>
        {displaySources.length === 0 ? (
          <Typography.Text type="secondary">还没有可展示的入湖源；请先在「源湖入库」上传</Typography.Text>
        ) : (
          <Table
            size="small"
            rowKey="source_id"
            loading={loadingSources}
            pagination={{ pageSize: 20, hideOnSinglePage: true }}
            dataSource={[...displaySources].sort((a, b) =>
              String(b.created_at || '').localeCompare(String(a.created_at || '')),
            )}
            columns={[
              {
                title: '选用',
                width: 72,
                render: (_: unknown, row: PlatformSourceRecord) => (
                  <Checkbox
                    data-testid={`lake-run-source-check-${row.source_id}`}
                    checked={selectedIds.includes(row.source_id)}
                    onChange={(e) => toggleSelected(row.source_id, e.target.checked)}
                  />
                ),
              },
              {
                title: '采集批',
                width: 140,
                render: (_: unknown, row: PlatformSourceRecord) => {
                  const id = collectionKey(row)
                  return (
                    <Tag color="blue" data-testid="lake-collection-tag">
                      {id.length > 12 ? `${id.slice(0, 10)}…` : id}
                    </Tag>
                  )
                },
              },
              {
                title: '类型',
                dataIndex: 'kind',
                width: 100,
                render: (kind: string) => <Tag>{kindLabel(kind as LakeKind)}</Tag>,
              },
              {
                title: '文件',
                render: (_: unknown, row: PlatformSourceRecord) => (
                  <Space>
                    <span>{row.filename || row.source_id}</span>
                    {row.kind === 'image' ? <Tag color="orange">仅入湖</Tag> : null}
                  </Space>
                ),
              },
              {
                title: '入湖时间',
                dataIndex: 'created_at',
                width: 180,
                render: (v: string | null | undefined) => v || '—',
              },
            ]}
          />
        )}
      </div>

      <Space>
        <Button
          data-testid="lake-run-preflight"
          disabled={!dataTypeId || !selectedIds.length}
          onClick={() => void runPreflight()}
        >
          预检
        </Button>
        <Button
          type="primary"
          icon={<PlayCircleOutlined />}
          data-testid="lake-run-create-run"
          disabled={!preflight?.ok}
          loading={running}
          onClick={() => void createRun()}
        >
          创建运行
        </Button>
      </Space>
      {preflight ? (
        <Alert
          type={preflight.ok ? 'success' : 'error'}
          showIcon
          message={preflight.ok ? '预检通过' : '预检失败'}
          description={`源类型：${(preflight.source_kinds || selectedSources.map((s) => s.kind)).join('、') || '—'}；算子：${
            (preflight.ops || []).join('、') || '—'
          }${preflight.missing?.length ? `；缺：${preflight.missing.join('、')}` : ''}`}
        />
      ) : null}
      {selectedSources.some((item) => item.kind === 'image') ? (
        <Alert
          type="warning"
          showIcon
          message="图片第一切片仅支持入湖"
          description="含图片的绑定当前不保证执行通过；建议先用 rosbag / 视频 / 音频 / 文本验证闭环。"
        />
      ) : null}
    </Space>
  )
}
