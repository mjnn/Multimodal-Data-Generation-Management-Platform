import { DeleteOutlined } from '@ant-design/icons'
import { Button, Input, Select, Space, Typography } from 'antd'
import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'
import type {
  PipelineBinding,
  PipelineStep,
  PlatformOperator,
  RecipeOverview,
  ViewCard,
  ViewWidget,
} from '../../api/types'
import {
  asBindingList,
  bindingOptions,
  decodeBinding,
  encodeBinding,
  slotsFromSteps,
} from '../../utils/recipePipeline'
import { PipelineCardShell } from './PipelineCardShell'
import './PipelineOrchestrator.css'
import './OverviewPreview.css'

type Surface = 'list' | 'detail'

type Props = {
  overview: RecipeOverview
  onChange: (next: RecipeOverview) => void
  widgets: ViewWidget[]
  steps: PipelineStep[]
  operators: PlatformOperator[]
  typeProvides: Record<string, string[]>
}

export function OverviewComposer({ overview, onChange, widgets, steps, operators, typeProvides }: Props) {
  return (
    <div className="overview-compose" data-testid="overview-composer" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <OverviewSurface
        surface="detail"
        title="展示页"
        cards={overview.detail}
        widgets={widgets.filter((w) => w.surface === 'detail')}
        steps={steps}
        operators={operators}
        typeProvides={typeProvides}
        onChange={(detail) => onChange({ ...overview, detail })}
      />
    </div>
  )
}

function OverviewSurface({
  surface,
  title,
  cards,
  widgets,
  steps,
  operators,
  typeProvides,
  onChange,
}: {
  surface: Surface
  title: string
  cards: ViewCard[]
  widgets: ViewWidget[]
  steps: PipelineStep[]
  operators: PlatformOperator[]
  typeProvides: Record<string, string[]>
  onChange: (cards: ViewCard[]) => void
}) {
  const dragFromRef = useRef<number | null>(null)
  const overRef = useRef<number | null>(null)
  const [dragFrom, setDragFrom] = useState<number | null>(null)
  const [dragOver, setDragOver] = useState<number | null>(null)

  const add = (widgetId: string) => {
    onChange([...cards, { key: `${surface}-${widgetId}-${Date.now()}`, widget_id: widgetId, bindings: {} }])
  }

  const patch = (index: number, next: ViewCard) => {
    const copy = [...cards]
    copy[index] = next
    onChange(copy)
  }

  const beginDrag = (index: number, e: ReactPointerEvent<HTMLButtonElement>) => {
    dragFromRef.current = index
    overRef.current = index
    setDragFrom(index)
    setDragOver(index)
    e.currentTarget.setPointerCapture(e.pointerId)
  }

  useEffect(() => {
    if (dragFrom == null) return
    const onMove = (e: PointerEvent) => {
      const el = document.elementFromPoint(e.clientX, e.clientY)
      const wrap = el?.closest(`[data-ov-surface="${surface}"][data-ov-index]`) as HTMLElement | null
      if (!wrap) return
      const idx = Number(wrap.dataset.ovIndex)
      if (!Number.isFinite(idx) || overRef.current === idx) return
      overRef.current = idx
      setDragOver(idx)
    }
    const onUp = () => {
      const from = dragFromRef.current
      const to = overRef.current
      dragFromRef.current = null
      overRef.current = null
      setDragFrom(null)
      setDragOver(null)
      if (from == null || to == null || from === to) return
      if (from < 0 || to < 0 || from >= cards.length || to >= cards.length) return
      const copy = [...cards]
      const [item] = copy.splice(from, 1)
      copy.splice(to, 0, item)
      onChange(copy)
    }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
    return () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
    }
  }, [cards, dragFrom, onChange, surface])

  return (
    <div className="pipe-orch" data-testid={`overview-composer-${surface}`} style={{ marginBottom: 16 }}>
      <div className="pipe-orch__palette">
        <p className="pipe-orch__palette-kicker">{title}组件</p>
        {widgets.map((w) => {
          return (
            <button
              key={w.id}
              type="button"
              className="pipe-orch__op"
              data-testid={`overview-add-${w.id}`}
              onClick={() => add(w.id)}
            >
              <span>{w.title}</span>
            </button>
          )
        })}
      </div>
      <div className="pipe-orch__steps">
        {cards.length === 0 ? (
          <div className="pipe-orch__empty">从左侧点选组件填入{title}。</div>
        ) : (
          cards.map((card, index) => {
            const spec = widgets.find((w) => w.id === card.widget_id)
            return (
              <div key={card.key} data-ov-surface={surface} data-ov-index={index}>
                <OverviewWidgetCard
                  card={card}
                  spec={spec}
                  steps={steps}
                  operators={operators}
                  typeProvides={typeProvides}
                  dragging={dragFrom === index}
                  dragOver={dragOver === index}
                  onHandlePointerDown={(e) => beginDrag(index, e)}
                  onChange={(next) => patch(index, next)}
                  onRemove={() => onChange(cards.filter((_, i) => i !== index))}
                />
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}

function OverviewWidgetCard({
  card,
  spec,
  steps,
  operators,
  typeProvides,
  dragging,
  dragOver,
  onHandlePointerDown,
  onChange,
  onRemove,
}: {
  card: ViewCard
  spec?: ViewWidget
  steps: PipelineStep[]
  operators: PlatformOperator[]
  typeProvides: Record<string, string[]>
  dragging?: boolean
  dragOver?: boolean
  onHandlePointerDown?: (e: ReactPointerEvent<HTMLButtonElement>) => void
  onChange: (next: ViewCard) => void
  onRemove: () => void
}) {
  const needs = spec?.needs || []
  const slots = slotsFromSteps(steps)
  const options = needs.length
    ? bindingOptions({
        neededTypes: needs,
        slots,
        upstream: steps,
        operators,
        typeProvides,
      })
    : []
  const bind = asBindingList(card.bindings?.in)
  return (
    <PipelineCardShell
      testId={`overview-card-${card.widget_id}`}
      title={spec?.title || card.widget_id}
      subtitle={card.widget_id}
      summary={spec?.description}
      dragging={dragging}
      dragOver={dragOver}
      onHandlePointerDown={onHandlePointerDown}
      extra={
        <Button size="small" danger icon={<DeleteOutlined />} onClick={onRemove} data-testid={`overview-remove-${card.widget_id}`} />
      }
    >
      {spec?.description ? (
        <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginBottom: needs.length ? 8 : 0 }}>
          {spec.description}
        </Typography.Paragraph>
      ) : null}
      {needs.length ? (
        <div data-testid={`overview-bind-${card.widget_id}`}>
          <Space direction="vertical" size={4} style={{ width: '100%' }}>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              绑定数据源或管线产物（可选）
            </Typography.Text>
            <Select
              allowClear
              showSearch
              optionFilterProp="label"
              mode="multiple"
              placeholder={options.length ? '数据源或上游产出' : '无兼容输入'}
              style={{ width: '100%' }}
              options={options.map((o) => ({ value: o.value, label: o.label }))}
              value={bind.map(encodeBinding).filter(Boolean)}
              onChange={(vals: string[]) => {
                const next: PipelineBinding[] = []
                for (const v of vals) {
                  const decoded = decodeBinding(v)
                  if (decoded) next.push(decoded)
                }
                onChange({ ...card, bindings: next.length ? { in: next } : {} })
              }}
            />
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              同步组（同名卡片共用播放头）
            </Typography.Text>
            <Input
              data-testid="overview-sync-group"
              allowClear
              placeholder="留空则独立"
              value={card.sync_group || ''}
              onChange={(e) => {
                const v = e.target.value.trim()
                onChange({ ...card, sync_group: v || undefined })
              }}
            />
          </Space>
        </div>
      ) : (
        <div data-testid={`overview-bind-${card.widget_id}`}>
          <Space direction="vertical" size={4} style={{ width: '100%' }}>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              同步组（同名卡片共用播放头）
            </Typography.Text>
            <Input
              data-testid="overview-sync-group"
              allowClear
              placeholder="留空则独立"
              value={card.sync_group || ''}
              onChange={(e) => {
                const v = e.target.value.trim()
                onChange({ ...card, sync_group: v || undefined })
              }}
            />
          </Space>
        </div>
      )}
    </PipelineCardShell>
  )
}

export function OverviewPreview({
  overview,
  widgets,
}: {
  overview: RecipeOverview
  widgets: ViewWidget[]
}) {
  const byId = new Map(widgets.map((w) => [w.id, w]))
  const detail = overview.detail || []
  return (
    <div className="overview-preview" data-testid="overview-preview">
      <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 8 }}>
        预览：Clip 详情页将按此顺序叠卡（示意，非真实数据）。
      </Typography.Text>
      <div className="overview-preview__cols">
        <PreviewColumn title="展示页" testId="overview-preview-detail" cards={detail} byId={byId} />
      </div>
    </div>
  )
}

function PreviewColumn({
  title,
  testId,
  cards,
  byId,
}: {
  title: string
  testId: string
  cards: ViewCard[]
  byId: Map<string, ViewWidget>
}) {
  return (
    <div className="overview-preview__col" data-testid={testId}>
      <div className="overview-preview__col-title">{title}</div>
      {cards.length === 0 ? (
        <div className="overview-preview__empty">尚未添加组件</div>
      ) : (
        cards.map((card) => {
          const spec = byId.get(card.widget_id)
          return (
            <div
              key={card.key}
              className="overview-preview__card"
              data-testid={`overview-preview-card-${card.widget_id}`}
            >
              <div className="overview-preview__card-title">{spec?.title || card.widget_id}</div>
              <div className="overview-preview__card-id">{card.widget_id}</div>
            </div>
          )
        })
      )}
    </div>
  )
}
