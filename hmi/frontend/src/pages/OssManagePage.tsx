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
  Spin,
  Table,
  Typography,
  message,
} from 'antd'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import type { OssBagPipeline, OssInfo, OssListItem } from '../api/types'
import { UploadPipelineProgress } from '../components/UploadPipelineProgress'
import { OssShortcutBar } from '../components/oss/OssShortcutBar'
import { ContentCard, PageHeader, PageStack } from '../components/ui'
import { useDataSourceMode } from '../context/DataSourceModeContext'
import { downloadOssObject } from '../utils/ossDownload'

const PIPELINE_SESSION_PREFIX = 'hmi:oss-bag-pipeline:'

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
  const [pipelineOpen, setPipelineOpen] = useState(false)
  const [pipelineLoading, setPipelineLoading] = useState(false)
  const [pipelineKey, setPipelineKey] = useState('')
  const [pipeline, setPipeline] = useState<OssBagPipeline | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
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

  const loadPipeline = useCallback(async (key: string, refresh = false) => {
    setPipelineKey(key)
    if (!refresh) {
      try {
        const cached = sessionStorage.getItem(`${PIPELINE_SESSION_PREFIX}${key}`)
        if (cached) {
          setPipeline(JSON.parse(cached) as OssBagPipeline)
        }
      } catch {
        /* ignore stale cache */
      }
    }
    setPipelineLoading(true)
    try {
      const p = await api.getOssBagPipeline(key, refresh)
      setPipeline(p)
      sessionStorage.setItem(`${PIPELINE_SESSION_PREFIX}${key}`, JSON.stringify(p))
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setPipelineLoading(false)
    }
  }, [])

  const showPipeline = (key: string) => {
    setPipelineOpen(true)
    void loadPipeline(key)
  }

  useEffect(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
    if (!pipelineOpen || !pipelineKey || pipeline?.pipeline_status !== 'running') return
    pollRef.current = setInterval(() => {
      void loadPipeline(pipelineKey, true)
    }, 8000)
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [pipelineOpen, pipelineKey, pipeline?.pipeline_status, loadPipeline])

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
        </Typography.Text>

        <Table
          rowKey="key"
          loading={loading}
          dataSource={items}
          pagination={false}
          columns={[
            {
              title: '名称',
              dataIndex: 'name',
              render: (name: string, r) =>
                r.type === 'dir' ? (
                  <a onClick={() => enterDir(r.key)}>
                    <FolderOpenOutlined style={{ marginRight: 6 }} />
                    {name}/
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
                <Space size={4}>
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
                    <Button type="link" size="small" onClick={() => showPipeline(r.key)}>
                      管线
                    </Button>
                  )}
                  <Popconfirm title={`确认删除 ${r.name}${r.type === 'dir' ? ' 及下属文件' : ''}？`} onConfirm={() => onDelete(r)}>
                    <Button type="link" size="small" danger icon={<DeleteOutlined />}>
                      删除
                    </Button>
                  </Popconfirm>
                </Space>
              ),
            },
          ]}
        />
      </ContentCard>

      {pipelineOpen && (
        <ContentCard
          title="Bag 管线状态"
          extra={
            <Space>
              <Button
                icon={<ReloadOutlined />}
                loading={pipelineLoading}
                onClick={() => pipelineKey && loadPipeline(pipelineKey, true)}
              >
                刷新
              </Button>
              <Button onClick={() => { setPipelineOpen(false); setPipelineKey('') }}>关闭</Button>
              {pipeline?.clip_id && pipeline.pipeline_status === 'completed' ? (
                <Button
                  type="primary"
                  onClick={() => navigate(`/clips/${encodeURIComponent(pipeline.clip_id!)}`)}
                >
                  进入时间轴
                </Button>
              ) : null}
            </Space>
          }
        >
          <Spin spinning={pipelineLoading}>
            <Typography.Text code>{pipeline?.oss_key ?? pipelineKey}</Typography.Text>
            {pipeline?.pipeline_steps?.length ? (
              <UploadPipelineProgress
                steps={pipeline.pipeline_steps}
                clipId={pipeline.clip_id ?? undefined}
                runId={pipeline.run_id ?? undefined}
              />
            ) : (
              <Typography.Text type="secondary">暂无步骤数据</Typography.Text>
            )}
          </Spin>
        </ContentCard>
      )}
    </PageStack>
  )
}
