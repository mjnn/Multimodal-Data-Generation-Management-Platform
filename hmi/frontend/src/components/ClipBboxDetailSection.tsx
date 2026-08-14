import { BorderOuterOutlined } from '@ant-design/icons'
import { Empty, Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useEffect, useState } from 'react'
import { api } from '../api'
import type { ClipBboxDetection } from '../api/types'
import { apiErrorMessage } from '../utils/apiError'

function fmtScore(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return '—'
  if (v < 0 || v > 1) return '—'
  return v.toFixed(2)
}

function fmtCoord(n: number): string {
  return Number.isFinite(n) ? n.toFixed(1) : '—'
}

type Props = {
  clipId: string
  runId: string
  cursorNs: number
  selectedBoxKey?: string | null
  onSelectBox?: (key: string | null) => void
  refreshToken?: number
}

export function ClipBboxDetailSection({
  clipId,
  runId,
  cursorNs,
  selectedBoxKey,
  onSelectBox,
  refreshToken = 0,
}: Props) {
  const [loading, setLoading] = useState(false)
  const [hasBboxes, setHasBboxes] = useState(false)
  const [detections, setDetections] = useState<ClipBboxDetection[]>([])
  const [message, setMessage] = useState<string | null>(null)

  useEffect(() => {
    if (!clipId || !runId) return
    let cancelled = false
    setLoading(true)
    void api
      .getClipBboxes(clipId, runId, { timestamp_ns: cursorNs, window_ms: 200 })
      .then((res) => {
        if (cancelled) return
        setHasBboxes(res.has_bboxes)
        setDetections(res.detections ?? [])
        setMessage(res.message ?? null)
      })
      .catch((e: unknown) => {
        if (cancelled) return
        setHasBboxes(false)
        setDetections([])
        const detail = apiErrorMessage(e, '')
        const status = (e as { response?: { status?: number } })?.response?.status
        if (status === 404) {
          setMessage('BBox 接口不存在（404）：请重启 HMI 后端以加载 /api/clips/.../bboxes')
        } else if (detail) {
          setMessage(`加载 BBox 失败：${detail}`)
        } else {
          setMessage('加载 BBox 失败')
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [clipId, runId, cursorNs, refreshToken])

  const columns: ColumnsType<ClipBboxDetection> = [
    {
      title: '相机',
      dataIndex: 'camera',
      width: 88,
      render: (v) => <Tag>{v || '—'}</Tag>,
    },
    {
      title: '坐标 (x1,y1)–(x2,y2)',
      key: 'xyxy',
      width: 200,
      render: (_, r) => (
        <Typography.Text code style={{ fontSize: 11 }}>
          ({fmtCoord(r.x1)},{fmtCoord(r.y1)})–({fmtCoord(r.x2)},{fmtCoord(r.y2)})
        </Typography.Text>
      ),
    },
    {
      title: '识别信息',
      dataIndex: 'display_label',
      ellipsis: true,
      render: (v, r) => (
        <span>
          <Typography.Text strong>{v || r.element}</Typography.Text>
          {r.gender || r.age_range || r.age_approx != null ? (
            <Typography.Text type="secondary" style={{ display: 'block', fontSize: 11 }}>
              {[
                r.gender ? `性别 ${r.gender}` : null,
                r.age_approx != null
                  ? `年龄 ~${r.age_approx}`
                  : r.age_range
                    ? `年龄段 ${r.age_range}`
                    : null,
              ]
                .filter(Boolean)
                .join(' · ')}
            </Typography.Text>
          ) : null}
        </span>
      ),
    },
    {
      title: '检测置信度',
      dataIndex: 'score',
      width: 96,
      render: (v) => fmtScore(v),
    },
    {
      title: '性别置信度',
      dataIndex: 'gender_score',
      width: 96,
      render: (v) => fmtScore(v),
    },
    {
      title: '年龄置信度',
      dataIndex: 'age_score',
      width: 96,
      render: (v) => fmtScore(v),
    },
  ]

  if (!hasBboxes && !loading) {
    return (
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description={
          message ||
          '本 Clip 无 bboxes.jsonl。请在校核页「带可编辑框」中新建并保存本帧。'
        }
        style={{ margin: '8px 0' }}
      />
    )
  }

  if (!loading && detections.length === 0) {
    return (
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description="当前时刻 ±200ms 内无检测框。请在校核页「带可编辑框」中新建后保存本帧。"
        style={{ margin: '8px 0' }}
      />
    )
  }

  return (
    <div data-testid="bbox-detail-section">
      <Typography.Paragraph type="secondary" style={{ fontSize: 12, margin: '0 0 8px' }}>
        切换到「带识别框预览」可只读查看当前 jsonl 框；新建 / 删框 / 调大小 / 改识别内容请到校核页「带可编辑框」。
      </Typography.Paragraph>
      <Table<ClipBboxDetection>
      size="small"
      loading={loading}
      rowKey={(r) => `${r.camera}:${r.timestamp_ns}:${r.box_index ?? 0}`}
      columns={columns}
      dataSource={detections}
      pagination={false}
      scroll={{ x: 780 }}
      locale={{ emptyText: '无检测结果' }}
      rowClassName={(r) => {
        const key = `${r.camera}:${r.timestamp_ns}:${r.box_index ?? 0}`
        return key === selectedBoxKey ? 'bbox-detail-row--selected' : ''
      }}
      onRow={(r) => ({
        onClick: () => {
          const key = `${r.camera}:${r.timestamp_ns}:${r.box_index ?? 0}`
          onSelectBox?.(key === selectedBoxKey ? null : key)
        },
        style: { cursor: onSelectBox ? 'pointer' : undefined },
      })}
    />
    </div>
  )
}

export function clipBboxCollapseLabel() {
  return (
    <Typography.Text strong>
      <BorderOuterOutlined /> BBox 识别
    </Typography.Text>
  )
}
