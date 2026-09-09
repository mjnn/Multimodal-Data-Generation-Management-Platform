import { PlayCircleOutlined } from '@ant-design/icons'
import { Alert, Button, Card, Checkbox, Select, Space, Table, Tag, Typography, message } from 'antd'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../../api'
import type {
  DataTypeRecipe,
  DataTypeSlot,
  PlatformRunPreflight,
  PlatformSourceRecord,
  PlatformSourceUnit,
  SlotAssignment,
} from '../../api/types'
import { rememberDataTypeId } from '../../context/DataTypeWorkspaceContext'
import { apiErrorMessage } from '../../utils/apiError'

import { IMAGE_EXTS, normalizeSourceKind } from '../../utils/fileKinds'

function kindLabel(kind: string): string {
  return normalizeSourceKind(kind) || kind
}

function collectionKey(row: PlatformSourceRecord): string {
  return String(row.collection_id || row.source_id)
}

function slotKinds(slot: DataTypeSlot): Set<string> {
  const kinds = new Set<string>()
  for (const k of slot.kinds || []) {
    kinds.add(normalizeSourceKind(k) || k)
  }
  return kinds
}

function slotTitle(slot: DataTypeSlot): string {
  return (slot.title || slot.id).trim() || slot.id
}

function sourcesForSlot(slot: DataTypeSlot, sources: PlatformSourceRecord[]): PlatformSourceRecord[] {
  const kinds = slotKinds(slot)
  if (!kinds.size) return sources
  return sources.filter((s) => kinds.has(normalizeSourceKind(s.kind) || s.kind))
}

function slotError(slot: DataTypeSlot, ids: string[]): string | null {
  const n = ids.length
  const min = slot.cardinality_min ?? 1
  const max = slot.cardinality_max ?? min
  const title = slotTitle(slot)
  if (slot.required && n === 0) return `${title}：需要 ${min}–${max} 个文件，已选 ${n}`
  if (n === 0) return null
  if (n < min || n > max) return `${title}：需要 ${min}–${max} 个文件，已选 ${n}`
  return null
}

function buildAssignments(slots: DataTypeSlot[], selectedBySlot: Record<string, string[]>): SlotAssignment[] {
  return slots
    .filter((slot) => slot.required || (selectedBySlot[slot.id] || []).length > 0)
    .map((slot) => ({ slot_id: slot.id, source_ids: selectedBySlot[slot.id] || [] }))
}

function unitDisplayTitle(unit: PlatformSourceUnit): string {
  const title = (unit.title || '').trim()
  if (title) return title
  const names = unit.members.map((m) => m.filename || m.source_id).filter(Boolean)
  return names.slice(0, 3).join(' + ') || unit.unit_id
}

function autoFillFromMembers(slots: DataTypeSlot[], members: PlatformSourceRecord[]): Record<string, string[]> {
  const used = new Set<string>()
  const next: Record<string, string[]> = {}
  for (const slot of slots) {
    const kinds = slotKinds(slot)
    const matches = members.filter(
      (m) => !used.has(m.source_id) && kinds.has(normalizeSourceKind(m.kind) || m.kind),
    )
    const min = Math.max(1, slot.cardinality_min ?? 1)
    const take = matches.slice(0, min)
    next[slot.id] = take.map((m) => m.source_id)
    take.forEach((m) => used.add(m.source_id))
  }
  return next
}

type LakeRunBindPanelProps = {
  initialDataTypeId?: string
  onDataTypeIdChange?: (id: string) => void
}

/** 管线管理 · 数据选择：先选类型 → 再勾选湖中符合要求的文件 → 预检 → 自动 Sample+Run */
export function LakeRunBindPanel({ initialDataTypeId, onDataTypeIdChange }: LakeRunBindPanelProps) {
  const navigate = useNavigate()
  const [sources, setSources] = useState<PlatformSourceRecord[]>([])
  const [units, setUnits] = useState<PlatformSourceUnit[]>([])
  const [selectedUnitId, setSelectedUnitId] = useState<string | undefined>()
  const [selectedBySlot, setSelectedBySlot] = useState<Record<string, string[]>>({})
  const [dataTypes, setDataTypes] = useState<DataTypeRecipe[]>([])
  const [dataTypeId, setDataTypeId] = useState<string | undefined>(initialDataTypeId)
  const [preflight, setPreflight] = useState<PlatformRunPreflight | null>(null)
  const [loadingSources, setLoadingSources] = useState(false)
  const [running, setRunning] = useState(false)

  const selectedRecipe = useMemo(
    () => dataTypes.find((item) => item.id === dataTypeId) ?? null,
    [dataTypes, dataTypeId],
  )

  const slots = selectedRecipe?.slots || []
  const usesUnits = slots.length >= 2
  const requiredSlotCount = slots.filter((slot) => slot.required).length

  const selectedIds = useMemo(() => {
    const seen = new Set<string>()
    const out: string[] = []
    for (const ids of Object.values(selectedBySlot)) {
      for (const id of ids) {
        if (seen.has(id)) continue
        seen.add(id)
        out.push(id)
      }
    }
    return out
  }, [selectedBySlot])

  const selectedSources = useMemo(
    () => sources.filter((item) => selectedIds.includes(item.source_id)),
    [sources, selectedIds],
  )

  const takenByOther = useMemo(() => {
    const map = new Map<string, string>()
    for (const [slotId, ids] of Object.entries(selectedBySlot)) {
      for (const id of ids) map.set(id, slotId)
    }
    return map
  }, [selectedBySlot])

  const blockErrors = useMemo(
    () => slots.map((slot) => slotError(slot, selectedBySlot[slot.id] || [])).filter((msg): msg is string => Boolean(msg)),
    [slots, selectedBySlot],
  )

  const assignments = useMemo(() => buildAssignments(slots, selectedBySlot), [slots, selectedBySlot])

  const filledSlotCount = useMemo(
    () => slots.filter((slot) => (selectedBySlot[slot.id] || []).length > 0).length,
    [slots, selectedBySlot],
  )

  const unitRequired = usesUnits && (requiredSlotCount >= 2 || filledSlotCount >= 2)
  const selectedUnit = units.find((item) => item.unit_id === selectedUnitId) ?? null
  const slotPool: PlatformSourceRecord[] = selectedUnit
    ? selectedUnit.members
    : requiredSlotCount >= 2
      ? []
      : sources

  const loadDataTypes = async () => {
    const res = await api.listDataTypes()
    setDataTypes((res.items || []).filter((item) => item.status === 'published'))
  }

  const loadSources = async (eligibleFor?: string) => {
    if (!eligibleFor) {
      setSources([])
      setUnits([])
      return
    }
    setLoadingSources(true)
    try {
      const [srcRes, unitRes] = await Promise.all([
        api.listPlatformSources(200, { eligibleFor }),
        api.listPlatformSourceUnits({ eligibleFor }),
      ])
      setSources(srcRes.items || [])
      setUnits(unitRes.items || [])
    } catch (e: unknown) {
      message.error(apiErrorMessage(e, '加载已入库源失败'))
    } finally {
      setLoadingSources(false)
    }
  }

  useEffect(() => {
    void loadDataTypes()
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mount once
  }, [])

  useEffect(() => {
    if (initialDataTypeId && !dataTypeId) setDataTypeId(initialDataTypeId)
  }, [initialDataTypeId, dataTypeId])

  useEffect(() => {
    setSelectedBySlot({})
    setSelectedUnitId(undefined)
    setPreflight(null)
    if (!dataTypeId) {
      setSources([])
      setUnits([])
      return
    }
    void loadSources(dataTypeId)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dataTypeId])

  const onSelectDataType = (value: string) => {
    setDataTypeId(value)
    onDataTypeIdChange?.(value)
    rememberDataTypeId(value)
  }

  const pickUnit = (unit: PlatformSourceUnit) => {
    setSelectedUnitId(unit.unit_id)
    setSelectedBySlot(autoFillFromMembers(slots, unit.members))
    setPreflight(null)
  }

  const clearUnit = () => {
    setSelectedUnitId(undefined)
    setSelectedBySlot({})
    setPreflight(null)
  }

  const runPreflight = async () => {
    if (!dataTypeId || !assignments.length) return
    if (unitRequired && !selectedUnitId) return
    try {
      const result = await api.preflightPlatformRun({
        data_type_id: dataTypeId,
        assignments,
        unit_id: selectedUnitId,
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
    if (!dataTypeId || !assignments.length || !preflight?.ok || running) return
    if (unitRequired && !selectedUnitId) return
    setRunning(true)
    try {
      const created = await api.createPlatformRun({
        data_type_id: dataTypeId,
        assignments,
        unit_id: selectedUnitId,
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

  const toggleSelected = (slotId: string, sourceId: string, checked: boolean) => {
    setSelectedBySlot((prev) => {
      const current = prev[slotId] || []
      const next = checked
        ? current.includes(sourceId)
          ? current
          : [...current, sourceId]
        : current.filter((id) => id !== sourceId)
      return { ...prev, [slotId]: next }
    })
    setPreflight(null)
  }

  const sourceColumns = (slot: DataTypeSlot) => [
    {
      title: '选用',
      width: 72,
      render: (_: unknown, row: PlatformSourceRecord) => {
        const owner = takenByOther.get(row.source_id)
        const taken = Boolean(owner && owner !== slot.id)
        return (
          <Checkbox
            data-testid={`lake-run-source-check-${row.source_id}`}
            checked={(selectedBySlot[slot.id] || []).includes(row.source_id)}
            disabled={taken}
            onChange={(e) => toggleSelected(slot.id, row.source_id, e.target.checked)}
          />
        )
      },
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
      render: (kind: string) => <Tag>{kindLabel(kind)}</Tag>,
    },
    {
      title: '文件',
      render: (_: unknown, row: PlatformSourceRecord) => (
        <Space>
          <span>{row.filename || row.source_id}</span>
          {(IMAGE_EXTS as readonly string[]).includes(normalizeSourceKind(row.kind) || row.kind) ? (
            <Tag color="orange">仅入湖</Tag>
          ) : null}
        </Space>
      ),
    },
    {
      title: '入湖时间',
      dataIndex: 'created_at',
      width: 180,
      render: (v: string | null | undefined) => v || '—',
    },
  ]

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }} data-testid="lake-run-bind-panel">
      <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
        先选择数据类型，再勾选湖里符合该类型数据源要求的文件。多槽类型请先选数据单元（自动填槽，可在单元内微调）。预检通过后创建运行；Sample
        由系统自动生成。入湖请前往「数据源」。
      </Typography.Paragraph>

      <Select
        data-testid="lake-run-data-type-select"
        placeholder="先选择数据类型"
        style={{ width: '100%', maxWidth: 480 }}
        value={dataTypeId}
        options={dataTypes.map((item) => ({
          value: item.id,
          label: `${item.title}（${item.id}）`,
        }))}
        onChange={onSelectDataType}
      />
      {selectedRecipe ? (
        <Typography.Text type="secondary">{selectedRecipe.purpose}</Typography.Text>
      ) : null}

      {usesUnits ? (
        <div data-testid="lake-run-unit-list">
          <Space style={{ marginBottom: 8 }} wrap>
            <Typography.Text strong>数据单元</Typography.Text>
            {requiredSlotCount < 2 ? (
              <Button size="small" disabled={!selectedUnitId} onClick={clearUnit}>
                不使用单元
              </Button>
            ) : null}
          </Space>
          {units.length === 0 ? (
            <Typography.Text type="secondary">
              {requiredSlotCount >= 2
                ? '请先在「数据源」把对应文件组成数据单元'
                : '可选：组成单元后一次填入多个数据源；只填一个槽时仍可直接勾散文件'}
            </Typography.Text>
          ) : (
            <Space direction="vertical" size={8} style={{ width: '100%' }}>
              {units.map((unit) => {
                const selected = selectedUnitId === unit.unit_id
                return (
                  <Card
                    key={unit.unit_id}
                    size="small"
                    hoverable
                    data-testid={`lake-run-unit-${unit.unit_id}`}
                    onClick={() => pickUnit(unit)}
                    style={{
                      cursor: 'pointer',
                      borderColor: selected ? '#1677ff' : undefined,
                    }}
                  >
                    <Space>
                      <Typography.Text strong>{unitDisplayTitle(unit)}</Typography.Text>
                      <Typography.Text type="secondary">
                        {unit.members.map((m) => m.filename || m.source_id).join('、')}
                      </Typography.Text>
                      {selected ? <Tag color="blue">已选</Tag> : null}
                    </Space>
                  </Card>
                )
              })}
            </Space>
          )}
        </div>
      ) : null}

      {unitRequired && !selectedUnitId ? (
        <Alert type="warning" showIcon message="请先选择数据单元，再预检开跑" />
      ) : null}

      <div data-testid="lake-run-sources-table">
        <Space style={{ marginBottom: 8 }}>
          <Button size="small" loading={loadingSources} onClick={() => void loadSources(dataTypeId)}>
            刷新
          </Button>
          <Typography.Text type="secondary">
            已选 {selectedIds.length} 个
            {dataTypeId ? '（仅显示符合当前类型的入湖文件）' : '（请先选数据类型）'}
            {selectedUnitId ? ' · 仅当前单元成员' : ''}
          </Typography.Text>
        </Space>
        {!dataTypeId ? (
          <Typography.Text type="secondary" data-testid="lake-run-pick-type-first">
            请先选择数据类型，再勾选湖中符合要求的数据
          </Typography.Text>
        ) : slots.length === 0 ? (
          <Typography.Text type="secondary">该类型没有数据源节点</Typography.Text>
        ) : requiredSlotCount >= 2 && !selectedUnitId ? (
          <Typography.Text type="secondary">请先选择数据单元，槽位将自动填入该单元文件</Typography.Text>
        ) : (
          <Space direction="vertical" size={16} style={{ width: '100%' }}>
            {slots.map((slot) => {
              const rows = sourcesForSlot(slot, slotPool)
              const min = slot.cardinality_min ?? 1
              const max = slot.cardinality_max ?? min
              const err = slotError(slot, selectedBySlot[slot.id] || [])
              const kindsTxt = (slot.kinds || []).map((k) => kindLabel(k)).join(' / ') || '—'
              return (
                <div key={slot.id} data-testid={`lake-run-slot-${slot.id}`}>
                  <Typography.Text strong>{slotTitle(slot)}</Typography.Text>
                  <Typography.Paragraph type="secondary" style={{ marginBottom: 8 }}>
                    {kindsTxt} · {min}–{max} 个
                    {slot.required ? ' · 必选' : ' · 可选'}
                    {` · 已选 ${(selectedBySlot[slot.id] || []).length}`}
                  </Typography.Paragraph>
                  {err ? (
                    <Alert type="warning" showIcon message={err} style={{ marginBottom: 8 }} />
                  ) : null}
                  {rows.length === 0 ? (
                    <Typography.Text type="secondary">没有匹配该数据源 kinds 的入湖文件</Typography.Text>
                  ) : (
                    <Table
                      size="small"
                      rowKey="source_id"
                      loading={loadingSources}
                      pagination={{ pageSize: 20, hideOnSinglePage: true }}
                      dataSource={[...rows].sort((a, b) =>
                        String(b.created_at || '').localeCompare(String(a.created_at || '')),
                      )}
                      columns={sourceColumns(slot)}
                    />
                  )}
                </div>
              )
            })}
          </Space>
        )}
      </div>

      {blockErrors.length ? (
        <Alert type="warning" showIcon message="分块未满足基数" description={blockErrors.join('；')} />
      ) : null}

      <Space>
        <Button
          data-testid="lake-run-preflight"
          disabled={!dataTypeId || !selectedIds.length || (unitRequired && !selectedUnitId)}
          onClick={() => void runPreflight()}
        >
          预检
        </Button>
        <Button
          type="primary"
          icon={<PlayCircleOutlined />}
          data-testid="lake-run-create-run"
          disabled={!preflight?.ok || blockErrors.length > 0 || (unitRequired && !selectedUnitId)}
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
      {selectedSources.some((item) =>
        (IMAGE_EXTS as readonly string[]).includes(normalizeSourceKind(item.kind) || item.kind),
      ) ? (
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
