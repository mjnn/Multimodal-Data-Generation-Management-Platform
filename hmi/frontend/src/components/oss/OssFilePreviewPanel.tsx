import { CloseOutlined, DownloadOutlined } from '@ant-design/icons'
import { Alert, Button, Space, Spin, Typography } from 'antd'
import { useCallback, useEffect, useState } from 'react'
import { api } from '../../api'
import type { OssFilePreview } from '../../api/types'
import { downloadOssObject } from '../../utils/ossDownload'

const PREVIEWABLE_SUFFIXES = new Set([
  '.json',
  '.jsonl',
  '.yaml',
  '.yml',
  '.txt',
  '.md',
  '.log',
  '.csv',
  '.xml',
  '.keep',
  '.sql',
  '.py',
  '.js',
  '.ts',
  '.html',
  '.css',
  '.toml',
  '.ini',
  '.cfg',
  '.env',
])

export function isOssPreviewableFile(name: string): boolean {
  const lower = name.toLowerCase()
  const dot = lower.lastIndexOf('.')
  if (dot < 0) return false
  return PREVIEWABLE_SUFFIXES.has(lower.slice(dot))
}

function formatSize(bytes: number): string {
  if (bytes <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let v = bytes
  let i = 0
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i++
  }
  return `${v.toFixed(i === 0 ? 0 : 1)} ${units[i]}`
}

type Props = {
  fileKey: string
  fileName: string
  onClose: () => void
}

export function OssFilePreviewPanel({ fileKey, fileName, onClose }: Props) {
  const [loading, setLoading] = useState(true)
  const [preview, setPreview] = useState<OssFilePreview | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setPreview(await api.previewOssFile(fileKey))
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(typeof detail === 'string' ? detail : e instanceof Error ? e.message : '预览失败')
      setPreview(null)
    } finally {
      setLoading(false)
    }
  }, [fileKey])

  useEffect(() => {
    void load()
  }, [load])

  return (
    <div
      style={{
        width: 420,
        flexShrink: 0,
        borderLeft: '1px solid var(--ant-color-border-secondary, #f0f0f0)',
        paddingLeft: 16,
        display: 'flex',
        flexDirection: 'column',
        minHeight: 360,
        maxHeight: '70vh',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8, marginBottom: 12 }}>
        <div style={{ minWidth: 0, flex: 1 }}>
          <Typography.Text strong style={{ display: 'block', wordBreak: 'break-all' }}>
            {fileName}
          </Typography.Text>
          {preview ? (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {formatSize(preview.size)}
              {preview.format !== 'text' ? ` · ${preview.format.toUpperCase()}` : ''}
            </Typography.Text>
          ) : null}
        </div>
        <Space size={4}>
          <Button
            type="text"
            size="small"
            icon={<DownloadOutlined />}
            title="下载"
            onClick={() => void downloadOssObject(fileKey, fileName)}
          />
          <Button type="text" size="small" icon={<CloseOutlined />} title="关闭预览" onClick={onClose} />
        </Space>
      </div>

      <Spin spinning={loading} style={{ flex: 1, minHeight: 200 }}>
        {error ? (
          <Alert type="error" message={error} showIcon />
        ) : preview ? (
          <>
            {preview.truncated ? (
              <Alert
                type="info"
                showIcon
                style={{ marginBottom: 8 }}
                message="内容已截断，仅展示前 256KB 或前 40 行（jsonl）"
              />
            ) : null}
            <pre
              style={{
                margin: 0,
                padding: 12,
                borderRadius: 8,
                background: 'var(--ant-color-fill-quaternary, #fafafa)',
                fontSize: 12,
                lineHeight: 1.5,
                overflow: 'auto',
                flex: 1,
                maxHeight: 'calc(70vh - 120px)',
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word',
              }}
            >
              {preview.preview}
            </pre>
          </>
        ) : null}
      </Spin>
    </div>
  )
}
