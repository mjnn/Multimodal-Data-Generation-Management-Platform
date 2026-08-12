import { CheckOutlined, CloseOutlined, MinusOutlined } from '@ant-design/icons'
import { Alert, Button, Input, Space, Tag, Typography, message } from 'antd'
import { useEffect, useState } from 'react'
import { api } from '../api'
import type { BboxQaRecord, BboxQaStatus } from '../api/types'
import { apiErrorMessage } from '../utils/apiError'

const STATUS_LABEL: Record<BboxQaStatus, string> = {
  bbox_ok: '框可用',
  bbox_bad: '框有问题',
  bbox_skip: '跳过',
}

const STATUS_COLOR: Record<BboxQaStatus, string> = {
  bbox_ok: 'success',
  bbox_bad: 'error',
  bbox_skip: 'default',
}

type Props = {
  clipId: string
  runId: string
  hasBboxPreview?: boolean
  initial?: BboxQaRecord | null
  onChange?: (qa: BboxQaRecord) => void
}

export function ReviewBboxQaBar({ clipId, runId, hasBboxPreview, initial, onChange }: Props) {
  const [qa, setQa] = useState<BboxQaRecord | null>(initial ?? null)
  const [note, setNote] = useState(initial?.note ?? '')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    setQa(initial ?? null)
    setNote(initial?.note ?? '')
  }, [clipId, runId, initial?.status, initial?.note, initial?.updated_at])

  if (!hasBboxPreview) {
    return (
      <Alert
        type="info"
        showIcon
        message="本 Clip 无带框预览"
        description="BBox 质量标记仅在有检测预览时可用；不影响 Taxonomy 字段校核。"
        data-testid="bbox-qa-unavailable"
      />
    )
  }

  const save = async (status: BboxQaStatus) => {
    setSaving(true)
    try {
      const res = await api.putBboxQa({
        clip_id: clipId,
        run_id: runId,
        status,
        note: note.trim() || null,
      })
      setQa(res.bbox_qa)
      onChange?.(res.bbox_qa)
      message.success(`已标记：${STATUS_LABEL[status]}`)
    } catch (e: unknown) {
      message.error(apiErrorMessage(e, '保存 BBox 质量标记失败'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div data-testid="bbox-qa-bar" className="review-bbox-qa-bar">
      <Space direction="vertical" size={8} style={{ width: '100%' }}>
        <Space wrap size={8} align="center">
          <Typography.Text strong>BBox 质量</Typography.Text>
          {qa?.status ? (
            <Tag color={STATUS_COLOR[qa.status]} data-testid="bbox-qa-current">
              当前：{STATUS_LABEL[qa.status]}
            </Tag>
          ) : (
            <Tag data-testid="bbox-qa-current">未标记</Tag>
          )}
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            与 Taxonomy 校核并行的轻量信号，不写入标签 / Dataset y
          </Typography.Text>
        </Space>
        <Space wrap size={8}>
          <Button
            size="small"
            type={qa?.status === 'bbox_ok' ? 'primary' : 'default'}
            icon={<CheckOutlined />}
            loading={saving}
            onClick={() => void save('bbox_ok')}
            data-testid="bbox-qa-ok"
          >
            框可用
          </Button>
          <Button
            size="small"
            danger={qa?.status === 'bbox_bad'}
            type={qa?.status === 'bbox_bad' ? 'primary' : 'default'}
            icon={<CloseOutlined />}
            loading={saving}
            onClick={() => void save('bbox_bad')}
            data-testid="bbox-qa-bad"
          >
            框有问题
          </Button>
          <Button
            size="small"
            type={qa?.status === 'bbox_skip' ? 'primary' : 'default'}
            icon={<MinusOutlined />}
            loading={saving}
            onClick={() => void save('bbox_skip')}
            data-testid="bbox-qa-skip"
          >
            跳过
          </Button>
        </Space>
        <Input.TextArea
          rows={2}
          maxLength={500}
          placeholder="可选备注（如：某路摄像头框飘移）"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          data-testid="bbox-qa-note"
        />
      </Space>
    </div>
  )
}
