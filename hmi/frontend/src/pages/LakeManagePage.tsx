import { InboxOutlined, SaveOutlined } from '@ant-design/icons'
import { Button, Card, List, Space, Table, Tabs, Tag, Typography, Upload, message } from 'antd'
import type { UploadProps } from 'antd'
import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../api'
import type { PlatformSourceRecord } from '../api/types'
import { ProductBrowsePanel } from '../components/lake/ProductBrowsePanel'
import { OssBrowserPanel } from '../components/oss/OssBrowserPanel'
import { ContentCard, PageHeader, PageStack } from '../components/ui'
import { useAuth } from '../auth/AuthContext'
import { canAccessOss } from '../auth/roles'
import { apiErrorMessage } from '../utils/apiError'
import { TEXT_EXTS, kindFromFilename, normalizeSourceKind } from '../utils/fileKinds'

type StagedLakeFile = {
  uid: string
  file: File
  kind: string
}

function classifyLakeFile(name: string): string | null {
  return kindFromFilename(name)
}

function textSchemaIdForFile(name: string): string | undefined {
  const kind = kindFromFilename(name)
  if (!kind || !(TEXT_EXTS as readonly string[]).includes(kind)) return undefined
  return name.toLowerCase().endsWith('.json') ? 'generic_json' : 'generic_text'
}

function kindLabel(kind: string): string {
  return normalizeSourceKind(kind) || kind
}

function newCollectionId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID()
  return `col-${Date.now()}-${Math.random().toString(16).slice(2)}`
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

async function fileToBase64(file: File): Promise<string> {
  const buf = await file.arrayBuffer()
  let binary = ''
  const bytes = new Uint8Array(buf)
  const chunkSize = 0x8000
  for (let i = 0; i < bytes.length; i += chunkSize) {
    const chunk = bytes.subarray(i, i + chunkSize)
    binary += String.fromCharCode(...chunk)
  }
  return btoa(binary)
}

type LakeTab = 'sources' | 'products' | 'oss'

function parseLakeTab(raw: string | null, allowOss: boolean): LakeTab {
  if (raw === 'products') return 'products'
  if (raw === 'oss' && allowOss) return 'oss'
  return 'sources'
}

export function LakeManagePage() {
  const { user } = useAuth()
  const allowOss = canAccessOss(user?.roles)
  const [searchParams, setSearchParams] = useSearchParams()
  const activeTab = parseLakeTab(searchParams.get('tab'), allowOss)

  const [staging, setStaging] = useState<StagedLakeFile[]>([])
  const [sources, setSources] = useState<PlatformSourceRecord[]>([])
  const [loadingSources, setLoadingSources] = useState(false)
  const [uploading, setUploading] = useState(false)

  const sortedSources = useMemo(
    () =>
      [...sources].sort((a, b) =>
        String(b.created_at || '').localeCompare(String(a.created_at || '')),
      ),
    [sources],
  )

  const loadSources = async () => {
    setLoadingSources(true)
    try {
      const res = await api.listPlatformSources(200)
      setSources((prev) => mergeSources(prev, res.items || []))
    } catch (e: unknown) {
      message.error(apiErrorMessage(e, '加载已入库源失败'))
    } finally {
      setLoadingSources(false)
    }
  }

  useEffect(() => {
    void loadSources()
  }, [])

  const setActiveTab = (tab: string) => {
    const next = new URLSearchParams(searchParams)
    if (tab === 'sources') next.delete('tab')
    else next.set('tab', tab)
    if (tab !== 'oss') next.delete('prefix')
    setSearchParams(next, { replace: true })
  }

  const beforeUpload: UploadProps['beforeUpload'] = (file) => {
    const kind = classifyLakeFile(file.name)
    if (!kind) {
      message.warning(`暂不支持文件：${file.name}`)
      return Upload.LIST_IGNORE
    }
    setStaging((prev) => {
      if (prev.some((item) => item.file.name === file.name && item.file.size === file.size)) return prev
      return [...prev, { uid: `${file.name}-${file.size}-${file.lastModified}`, file: file as File, kind }]
    })
    return Upload.LIST_IGNORE
  }

  const uploadToLake = async () => {
    if (!staging.length || uploading) return
    setUploading(true)
    const collectionId = newCollectionId()
    try {
      const next: PlatformSourceRecord[] = []
      for (const item of staging) {
        const created = await api.createPlatformSource({
          kind: item.kind,
          filename: item.file.name,
          text_schema_id: textSchemaIdForFile(item.file.name),
          content_b64: await fileToBase64(item.file),
          collection_id: collectionId,
        })
        next.push(created)
      }
      setSources((prev) => mergeSources(prev, next))
      setStaging([])
      message.success(`已入湖 ${next.length} 个源文件（采集批 ${collectionId.slice(0, 8)}…）`)
    } catch (e: unknown) {
      message.error(apiErrorMessage(e, '源文件入湖失败'))
    } finally {
      setUploading(false)
    }
  }

  const sourcesPanel = (
    <ContentCard>
      <Typography.Paragraph type="secondary">
        上传源文件并按采集批查看；同批不自动绑定。选类型、筛源、预检与开跑请到「管线管理 → 数据选择」。
      </Typography.Paragraph>
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        <Upload.Dragger
          accept=".bag,.mp4,.webm,.mov,.mkv,.avi,.wav,.mp3,.m4a,.flac,.ogg,.aac,.dat,.txt,.json,.md,.csv,.jpg,.jpeg,.png,.webp,.bmp"
          multiple
          beforeUpload={beforeUpload}
          showUploadList={false}
          data-testid="lake-upload-dragger"
        >
          <p className="ant-upload-drag-icon">
            <InboxOutlined />
          </p>
          <Typography.Text strong>拖入或选择要入湖的源文件</Typography.Text>
          <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
            同一次入湖共用一个采集批号。
          </Typography.Paragraph>
        </Upload.Dragger>

        {staging.length > 0 ? (
          <Card size="small" title="待入湖">
            <List
              size="small"
              dataSource={staging}
              renderItem={(item) => (
                <List.Item>
                  <Space>
                    <Tag>{kindLabel(item.kind)}</Tag>
                    <span>{item.file.name}</span>
                  </Space>
                </List.Item>
              )}
            />
            <Button
              type="primary"
              icon={<SaveOutlined />}
              loading={uploading}
              onClick={() => void uploadToLake()}
              style={{ marginTop: 12 }}
            >
              入湖
            </Button>
          </Card>
        ) : null}

        <div data-testid="lake-sources-table">
          <Space style={{ marginBottom: 8 }}>
            <Button size="small" loading={loadingSources} onClick={() => void loadSources()}>
              刷新
            </Button>
            <Typography.Text type="secondary">共 {sortedSources.length} 个源</Typography.Text>
          </Space>
          {sortedSources.length === 0 ? (
            <Typography.Text type="secondary">还没有入湖源</Typography.Text>
          ) : (
            <Table
              size="small"
              rowKey="source_id"
              loading={loadingSources}
              pagination={{ pageSize: 20, hideOnSinglePage: true }}
              dataSource={sortedSources}
              columns={[
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
                    <span>{row.filename || row.source_id}</span>
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
      </Space>
    </ContentCard>
  )

  const tabItems = [
    { key: 'sources', label: '源文件', children: sourcesPanel },
    { key: 'products', label: '产物浏览', children: <ProductBrowsePanel /> },
    ...(allowOss
      ? [
          {
            key: 'oss',
            label: 'OSS 浏览',
            children: <OssBrowserPanel />,
          },
        ]
      : []),
  ]

  return (
    <PageStack data-testid="lake-page">
      <PageHeader
        title="数据源"
        description="管理入湖源文件、浏览管线产物血缘，以及 OSS 对象；管线执行在「管线管理」。"
      />
      <Tabs activeKey={activeTab} onChange={setActiveTab} items={tabItems} />
    </PageStack>
  )
}
