import { Empty, Space, Tag, Typography } from 'antd'

import type { ReviewV2ClipCard as ClipCard, ReviewV2Task } from '../api/types'

import { ClipMediaPanel } from './ClipMediaPanel'
import { ContentCard } from './ui'
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

    <Space direction="vertical" size={12} style={{ width: '100%' }}>

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

      <ContentCard title="ASR 文本" className="review-workbench-asr">

        {card.asr_text?.trim() ? (

          <Typography.Paragraph className="clip-detail-asr" style={{ margin: 0 }}>

            {card.asr_text.trim()}

          </Typography.Paragraph>

        ) : (

          <Empty

            image={Empty.PRESENTED_IMAGE_SIMPLE}

            description="本 Clip 无 ASR 文本"

            style={{ margin: '8px 0' }}

          />

        )}

      </ContentCard>

    </Space>

  )

}

