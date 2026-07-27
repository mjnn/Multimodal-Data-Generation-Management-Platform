import { Tag } from 'antd'

import type { ReviewV2ClipCard as ClipCard, ReviewV2Task } from '../api/types'

import { ClipMediaPanel } from './ClipMediaPanel'
import { clipDisplayName } from '../utils/clipDisplay'



type Props = {

  task: ReviewV2Task

}



function parseAnchorTimestampNs(value: unknown): number | undefined {

  if (typeof value === 'number' && Number.isFinite(value)) return value

  if (typeof value === 'string' && value.trim()) {

    const parsed = Number(value)

    if (Number.isFinite(parsed)) return parsed

  }

  return undefined

}



function renderGateTags(card: ClipCard) {

  const gate = card.multi_ai_gate

  if (!gate) return null

  if (!gate.passed) {

    return (

      <Tag key="gate" color="orange">

        Gate 未通过

      </Tag>

    )

  }

  return null

}



export function ReviewClipMediaPanel({ task }: Props) {

  const { clip_card: card } = task



  return (

    <ClipMediaPanel

      clipId={task.clip_id}

      runId={task.run_id}

      initialTimestampNs={parseAnchorTimestampNs(card.anchor_timestamp_ns)}

      title={clipDisplayName({ clip_id: card.clip_id })}

      labelPreview={card.label_preview}

      testId="review-clip-card"

      metaTags={

        <>

          {renderGateTags(card)}

          {card.review_status ? (

            <Tag color={card.review_status === 'reviewed' ? 'success' : 'warning'}>

              {card.review_status === 'reviewed' ? 'Clip 已校核' : 'Clip 待校核'}

            </Tag>

          ) : null}

        </>

      }

    />

  )

}

