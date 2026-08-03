import {
  CloudServerOutlined,
  DeleteOutlined,
  DownloadOutlined,
  FolderOpenOutlined,
  ReloadOutlined,
} from '@ant-design/icons'
import {
  Breadcrumb,
  Button,
  Popconfirm,
  Space,
  Table,
  Typography,
  message,
} from 'antd'
import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import type { OssInfo, OssListItem } from '../api/types'
import { isOssPreviewableFile, OssFilePreviewPanel } from '../components/oss/OssFilePreviewPanel'
import { OssShortcutBar } from '../components/oss/OssShortcutBar'
import { ContentCard, PageHeader, PageStack } from '../components/ui'
import { useDataSourceMode } from '../context/DataSourceModeContext'
import { downloadOssObject } from '../utils/ossDownload'

function formatSize(bytes: number): string {
  if (bytes <= 0) return '—'
  const units = ['B', 'KB', 'MB', 'GB']
  let v = bytes
  let i = 0
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i++
  }
  return `${v.toFixed(i === 0 ? 0 : 1)} ${units[i]}`
}

export function OssManagePage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const { dataSource, dataRevision } = useDataSourceMode()
  const [info, setInfo] = useState<OssInfo | null>(null)
  const [prefix, setPrefix] = useState('')
  const [parentPrefix, setParentPrefix] = useState('')
  const [items, setItems] = useState<OssListItem[]>([])
  const [loading, setLoading] = useState(false)
  const [pipelineNavKey, setPipelineNavKey] = useState<string | null>(null)
  const [previewFile, setPreviewFile] = useState<{ key: string; name: string } | null>(null)
  const initialPrefix = searchParams.get('prefix') ?? ''

  const loadList = useCallback((p = prefix) => {
    setLoading(true)
    api
      .listOss(p)
      .then((res) => {
        setPrefix(res.prefix)
        setParentPrefix(res.parent_prefix)
        setItems(res.items)
      })
      .catch((e: Error) => message.error(e.message))
      .finally(() => setLoading(false))
  }, [prefix])

  useEffect(() => {
    api.getOssInfo().then(setInfo).catch(() => {})
    loadList(initialPrefix)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- refresh OSS view when local/cloud toggles
  }, [dataSource, dataRevision, initialPrefix])

  const enterDir = (key: string) => loadList(key)

  const breadcrumbItems = () => {
    const parts = prefix.replace(/\/$/, '').split('/').filter(Boolean)
    const crumbs = [{ title: <a onClick={() => loadList('')}>根目录</a> }]
    let acc = ''
    for (const part of parts) {
      acc += `${part}/`
      const p = acc
      crumbs.push({
        title: <a onClick={() => loadList(p)}>{part}</a>,
      })
    }
    return crumbs
  }

  const onDownload = async (key: string, name: string) => {
    try {
      await downloadOssObject(key, name)
    } catch (e) {
      message.error((e as Error).message)
    }
  }

  const onDelete = async (record: OssListItem) => {
    try {
      if (record.type === 'dir') {
        await api.deleteOssPrefix(record.key)
      } else {
        await api.deleteOssObject(record.key)
      }
      message.success('已删除')
      loadList(prefix)
    } catch (e) {
      message.error((e as Error).message)
    }
  }

  const goPipelineManage = async (key: string) => {
    setPipelineNavKey(key)
    try {
      const pipeline = await api.getOssBagPipeline(key, false)
      if (pipeline.clip_id && pipeline.run_id) {
        const params = new URLSearchParams({
          run_id: pipeline.run_id,
          clip_id: pipeline.clip_id,
        })
        navigate(`/pipeline?${params.toString()}`)
        return
      }
      navigate('/pipeline')
      message.info('该 bag 尚未登记 clip，请在管线管理查看上传队列')
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setPipelineNavKey(null)
    }
  }

  const openPreview = (record: OssListItem) => {
    if (record.type !== 'file' || !isOssPreviewableFile(record.name)) return
    setPreviewFile({ key: record.key, name: record.name })
  }

  return (
    <PageStack>
      <PageHeader
        title="OSS 管理"
        description="浏览本地磁盘或云端桶内产物；上传 rosbag 与自动同步请前往「管线管理」。"
        icon={<CloudServerOutlined />}
      />

      {info && (
        <ContentCard title={info.bucket}>
          {info.simulated ? (
            <Typography.Text type="secondary" style={{ display: 'block', marginBottom: 12, fontSize: 12 }}>
              模拟 OSS 根目录：<Typography.Text code>{info.endpoint}</Typography.Text>
            </Typography.Text>
          ) : null}
          <OssShortcutBar presets={info.root_prefixes} onNavigate={(p) => loadList(p)} />
        </ContentCard>
      )}

      <ContentCard
        title="对象列表"
        extra={
          <Space>
            <Button icon={<ReloadOutlined />} onClick={() => loadList(prefix)} loading={loading}>
              刷新
            </Button>
            <Button disabled={!parentPrefix && !prefix} onClick={() => loadList(parentPrefix)}>
              上级
            </Button>
          </Space>
        }
      >
        <Breadcrumb items={breadcrumbItems()} style={{ marginBottom: 12 }} />
        <Typography.Text type="secondary" style={{ display: 'block', marginBottom: 12, fontSize: 12 }}>
          当前路径：<Typography.Text code>{prefix || '/'}</Typography.Text>
          {previewFile ? (
            <>
              {' '}
              · 点击文件名预览文本/JSON；右侧为内容摘要
            </>
          ) : null}
        </Typography.Text>

        <div style={{ display: 'flex', alignItems: 'stretch', gap: 0 }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <Table
              rowKey="key"
              loading={loading}
              dataSource={items}
              pagination={false}
              onRow={(record) =>
                record.type === 'file' && isOssPreviewableFile(record.name)
                  ? {
                      onClick: () => openPreview(record),
                      style: { cursor: 'pointer' },
                    }
                  : {}
              }
              rowClassName={(record) =>
                previewFile?.key === record.key ? 'oss-row-preview-active' : ''
              }
              columns={[
                {
                  title: '名称',
                  dataIndex: 'name',
                  render: (name: string, r) =>
                    r.type === 'dir' ? (
                      <a
                        onClick={(e) => {
                          e.stopPropagation()
                          enterDir(r.key)
                        }}
                      >
                        <FolderOpenOutlined style={{ marginRight: 6 }} />
                        {name}/
                      </a>
                    ) : isOssPreviewableFile(name) ? (
                      <a
                        onClick={(e) => {
                          e.stopPropagation()
                          openPreview(r)
                        }}
                      >
                        {name}
                      </a>
                    ) : (
                      name
                    ),
                },
                {
                  title: '大小',
                  dataIndex: 'size',
                  width: 100,
                  render: (v: number, r) => (r.type === 'dir' ? '—' : formatSize(v)),
                },
                {
                  title: '修改时间',
                  dataIndex: 'last_modified',
                  width: 180,
                  render: (v: string | null) => (v ? api.formatDateTime(v) : '—'),
                },
                {
                  title: '操作',
                  width: 220,
                  render: (_, r) => (
                    <Space size={4} onClick={(e) => e.stopPropagation()}>
                      {r.type === 'file' && (
                        <Button
                          type="link"
                          size="small"
                          icon={<DownloadOutlined />}
                          onClick={() => void onDownload(r.key, r.name)}
                        >
                          下载
                        </Button>
                      )}
                      {r.type === 'file' && r.name.toLowerCase().endsWith('.bag') && (
                        <Button
                          type="link"
                          size="small"
                          loading={pipelineNavKey === r.key}
                          onClick={() => void goPipelineManage(r.key)}
                        >
                          管线
                        </Button>
                      )}
                      <Popconfirm
                        title={`确认删除 ${r.name}${r.type === 'dir' ? ' 及下属文件' : ''}？`}
                        onConfirm={() => onDelete(r)}
                      >
                        <Button type="link" size="small" danger icon={<DeleteOutlined />}>
                          删除
                        </Button>
                      </Popconfirm>
                    </Space>
                  ),
                },
              ]}
            />
          </div>

          {previewFile ? (
            <OssFilePreviewPanel
              fileKey={previewFile.key}
              fileName={previewFile.name}
              onClose={() => setPreviewFile(null)}
            />
          ) : null}
        </div>
      </ContentCard>
    </PageStack>
  )
}
