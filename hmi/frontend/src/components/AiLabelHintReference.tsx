import { Typography } from 'antd'

export type AiLabelHint = {
  confidence?: number | null
  evidence?: string | null
}

type Props = {
  confidence?: number | null
  evidence?: string | null
  className?: string
}

export function AiLabelHintReference({ confidence, evidence, className }: Props) {
  const hasConfidence = confidence != null && !Number.isNaN(Number(confidence))
  const evidenceText = evidence?.trim() ?? ''
  if (!hasConfidence && !evidenceText) return null

  return (
    <div className={className ?? 'review-ai-label-hint'}>
      {hasConfidence ? (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          置信度 {Math.round(Number(confidence) * 100)}%
        </Typography.Text>
      ) : null}
      {evidenceText ? (
        <Typography.Paragraph
          type="secondary"
          style={{ fontSize: 12, marginBottom: 0, marginTop: hasConfidence ? 4 : 0 }}
        >
          证据：{evidenceText}
        </Typography.Paragraph>
      ) : null}
    </div>
  )
}
