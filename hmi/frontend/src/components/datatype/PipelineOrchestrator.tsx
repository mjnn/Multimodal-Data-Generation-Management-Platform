import { Typography } from 'antd'
import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'
import type { PipelineStep, PlatformOperator } from '../../api/types'
import { sourceKindOptions } from '../../utils/fileKinds'
import { isLabelCard, isSourceCard, newSourceCard, newStepFromOp, nextSourceTitle, pinLabelLast, slotsFromSteps } from '../../utils/recipePipeline'
import { ComponentPalette } from './ComponentPalette'
import { PipelineSourceCard } from './PipelineSourceCard'
import { PipelineStepCard } from './PipelineStepCard'
import './PipelineOrchestrator.css'

type Props = {
  operators: PlatformOperator[]
  categoryTitles?: Record<string, string>
  typeProvides: Record<string, string[]>
  sourceKinds?: string[]
  steps: PipelineStep[]
  onChange: (steps: PipelineStep[]) => void
}

export function PipelineOrchestrator({
  operators,
  categoryTitles,
  typeProvides,
  sourceKinds,
  steps,
  onChange,
}: Props) {
  const slots = slotsFromSteps(steps)
  const kindOptions = sourceKindOptions(sourceKinds)
  const opTotal = steps.filter((s) => !isSourceCard(s)).length

  const add = (opId: string) => {
    if (opId === 'label' && steps.some(isLabelCard)) return
    const prior = steps.filter((s) => !isLabelCard(s))
    const key = `${opId}-${Date.now()}`
    const card = newStepFromOp({
      opId,
      key,
      operators,
      slots,
      upstream: prior,
      typeProvides,
    })
    const labelIdx = steps.findIndex(isLabelCard)
    const next = [...steps]
    if (opId === 'label' || labelIdx < 0) next.push(card)
    else next.splice(labelIdx, 0, card)
    onChange(pinLabelLast(next))
  }

  const lastSourceIndex = steps.reduce((acc, s, i) => (isSourceCard(s) ? i : acc), -1)
  const sourceRows = steps
    .map((step, index) => ({ step, index }))
    .filter((row) => isSourceCard(row.step))

  const addSource = () => {
    const card = newSourceCard({
      key: `src-${Date.now()}`,
      title: nextSourceTitle(steps),
      kinds: ['.mp4'],
    })
    const insertAt = lastSourceIndex >= 0 ? lastSourceIndex + 1 : 0
    const next = [...steps]
    next.splice(insertAt, 0, card)
    onChange(pinLabelLast(next))
  }

  const patch = (index: number, next: PipelineStep) => {
    const copy = [...steps]
    copy[index] = next
    onChange(copy)
  }

  const move = (index: number, delta: number) => {
    if (isLabelCard(steps[index])) return
    const dir = delta < 0 ? -1 : 1
    let dest = index + dir
    while (dest >= 0 && dest < steps.length && isSourceCard(steps[dest])) dest += dir
    if (dest < 0 || dest >= steps.length) return
    if (isLabelCard(steps[dest])) return
    moveTo(index, dest)
  }

  const moveTo = (from: number, to: number) => {
    if (from === to || from < 0 || to < 0 || from >= steps.length || to >= steps.length) return
    if (isLabelCard(steps[from])) return
    const labelIdx = steps.findIndex(isLabelCard)
    let dest = to
    if (labelIdx >= 0 && dest >= labelIdx) dest = labelIdx - 1
    if (dest < 0 || dest === from || dest >= steps.length) return
    const copy = [...steps]
    const [item] = copy.splice(from, 1)
    copy.splice(dest, 0, item)
    onChange(pinLabelLast(copy))
  }

  const dragFromRef = useRef<number | null>(null)
  const overRef = useRef<number | null>(null)
  const [dragFrom, setDragFrom] = useState<number | null>(null)
  const [dragOver, setDragOver] = useState<number | null>(null)

  const beginDrag = (index: number, e: ReactPointerEvent<HTMLButtonElement>) => {
    if (isLabelCard(steps[index])) return
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
      const wrap = el?.closest('[data-pipe-index]') as HTMLElement | null
      if (!wrap) return
      const idx = Number(wrap.dataset.pipeIndex)
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
      if (from == null || to == null) return
      moveTo(from, to)
    }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
    return () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
    }
  }, [dragFrom, steps, onChange])

  const remove = (index: number) => {
    if (isLabelCard(steps[index])) return
    const gone = steps[index]?.key
    onChange(
      pinLabelLast(
      steps
        .filter((_, i) => i !== index)
        .map((s) => {
          const bindings = { ...(s.bindings || {}) }
          let changed = false
          for (const [pid, raw] of Object.entries(bindings)) {
            if (Array.isArray(raw)) {
              const kept = raw.filter(
                (b) =>
                  !(b.kind === 'upstream' && b.step_key === gone) &&
                  !(b.kind === 'slot' && b.slot_id === gone),
              )
              if (kept.length !== raw.length) {
                changed = true
                if (kept.length) bindings[pid] = kept
                else delete bindings[pid]
              }
            } else if (raw.kind === 'upstream' && raw.step_key === gone) {
              delete bindings[pid]
              changed = true
            } else if (raw.kind === 'slot' && raw.slot_id === gone) {
              delete bindings[pid]
              changed = true
            }
          }
          return changed ? { ...s, bindings } : s
        }),
      ),
    )
  }

  return (
    <div className="pipe-orch" data-testid="pipeline-orchestrator">
      <ComponentPalette operators={operators} categoryTitles={categoryTitles} onAdd={add} />
      <div className="pipe-orch__steps">
        <PipelineSourceCard
          sources={sourceRows}
          kindOptions={kindOptions}
          onChangeRow={(index, next) => patch(index, next)}
          onRemoveRow={(index) => remove(index)}
          onAdd={addSource}
        />
        {steps.map((step, index) =>
          isSourceCard(step) ? null : (
              <div
                key={step.key}
                data-pipe-index={index}
                className="pipe-step-wrap"
              >
              <PipelineStepCard
                step={step}
                index={steps.slice(0, index).filter((s) => !isSourceCard(s)).length}
                total={opTotal}
                listIndex={index}
                listTotal={steps.length}
                pinnedLast={isLabelCard(step)}
                canMoveUp={!isLabelCard(step) && index > lastSourceIndex + 1}
                canMoveDown={
                  !isLabelCard(step) &&
                  (steps.findIndex(isLabelCard) >= 0
                    ? index < steps.findIndex(isLabelCard) - 1
                    : index < steps.length - 1)
                }
                slots={slots}
                upstream={steps.slice(0, index)}
                operators={operators}
                typeProvides={typeProvides}
                onChange={(next) => patch(index, next)}
                onMove={(delta) => move(index, delta)}
                onRemove={() => remove(index)}
                dragging={dragFrom === index}
                dragOver={dragOver === index}
                onHandlePointerDown={isLabelCard(step) ? undefined : (e) => beginDrag(index, e)}
              />
              </div>
          ),
        )}
        <Typography.Paragraph type="secondary" style={{ margin: 0, fontSize: 12 }}>
          打标器固定在最后一个节点（管线最终输出标签树），不能拖走或删除。点选其他算子会插到打标器前面。打标 / 向量化保存为 stages，不进入 preprocess。
        </Typography.Paragraph>
      </div>
    </div>
  )
}
