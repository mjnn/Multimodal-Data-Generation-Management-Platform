import {
  CloudServerOutlined,
  DeleteOutlined,
  DownloadOutlined,
  FolderAddOutlined,
  FolderOpenOutlined,
  ReloadOutlined,
  UploadOutlined,
} from '@ant-design/icons'
import {
  Alert,
  Breadcrumb,
  Button,
  Input,
  Modal,
  Popconfirm,
  Space,
  Skeleton,
  Spin,
  Switch,
  Table,
  Tag,
  Tooltip,
  Typography,
  Upload,
  message,
} from 'antd'
import type { UploadProps } from 'antd'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import type { BagPipelineStatus, OssBagPipeline, OssInfo, OssListItem, OssSyncPollerStatus } from '../api/types'
import { UploadPipelineProgress } from '../components/UploadPipelineProgress'
import { ContentCard, PageHeader, PageStack } from '../components/ui'

const PIPELINE_SESSION_PREFIX = 'hmi:oss-bag-pipeline:'

const BAG_PIPELINE_STATUS: Record<
  BagPipelineStatus,
  { color: string; text: string }
> = {
  not_discovered: { color: 'default', text: '未发现' },
  idle: { color: 'warning', text: '待启动' },
  running: { color: 'processing', text: '进行中' },
  completed: { color: 'success', text: '已完成' },
  failed: { color: 'error', text: '失败' },
}

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
  const [info, setInfo] = useState<OssInfo | null>(null)
  const [prefix, setPrefix] = useState('')
  const [parentPrefix, setParentPrefix] = useState('')
  const [items, setItems] = useState<OssListItem[]>([])
  const [loading, setLoading] = useState(false)
  const [pipelineOpen, setPipelineOpen] = useState(false)
  const [pipelineLoading, setPipelineLoading] = useState(false)
  const [pipelineKey, setPipelineKey] = useState('')
  const [pipeline, setPipeline] = useState<OssBagPipeline | null>(null)
  const [mkdirOpen, setMkdirOpen] = useState(false)
  const [syncStatus, setSyncStatus] = useState<OssSyncPollerStatus | null>(null)
  const [syncSaving, setSyncSaving] = useState(false)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const [newDirName, setNewDirName] = useState('')

  const loadList = useCallback(
    (p = prefix) => {
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
    },
    [prefix],
  )

  useEffect(() => {
    api.getOssInfo().then(setInfo).catch(() => {})
    api.getSyncPollerStatus().then(setSyncStatus).catch(() => {})
    loadList('')
  }, [])

  const onToggleAutoSync = async (checked: boolean) => {
    setSyncSaving(true)
    try {
      const status = await api.setSyncPollerEnabled(checked)
      setSyncStatus(status)
      message.success(checked ? '已开启 OSS 自动同步' : '已关闭 OSS 自动同步')
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setSyncSaving(false)
    }
  }

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

  const onUpload: UploadProps['customRequest'] = async ({ file, onSuccess, onError }) => {
    try {
      const f = file as File
      const res = await api.uploadOssFile(prefix, f)
      message.success(`已上传 ${res.key}`)
      onSuccess?.(res)
      loadList(prefix)
    } catch (e) {
      message.error('上传失败')
      onError?.(e as Error)
    }
  }

  const onDownload = async (key: string) => {
    try {
      const { url } = await api.getOssDownloadUrl(key)
      window.open(url, '_blank', 'noopener,noreferrer')
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

  const onMkdir = async () => {
    const name = newDirName.trim().replace(/[/\\]/g, '')
    if (!name) {
      message.warning('请输入目录名')
      return
    }
    try {
      await api.mkdirOss(`${prefix}${name}/`)
      message.success('目录已创建')
      setMkdirOpen(false)
      setNewDirName('')
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
        description="浏览与管理桶内文件；上传 .bag 到 rosbags/ 后由 Job0 discover 发现。DataWorks 管线调整期间 OSS 产物可能不可信，自动同步默认关闭。"
        icon={<CloudServerOutlined />}
      />

      <ContentCard title="OSS 自动同步">
        <Space direction="vertical" style={{ width: '100%' }} size={12}>
          <Alert
            type="warning"
            showIcon
            message="管线迁移提示"
            description="当前 DataWorks 正在调整为以 clip 为中心；在 manifest 验证通过前，请保持自动同步关闭，HMI 以本地 demo / 校核数据为准。"
          />
          <Space wrap align="center">
            <Switch
              checked={syncStatus?.auto_sync_enabled ?? false}
              loading={syncSaving}
              onChange={onToggleAutoSync}
              checkedChildren="开"
              unCheckedChildren="关"
            />
            <Typography.Text>
              自动同步 OSS 产物到本地（轮询 pipeline/dispatch/latest.json）
            </Typography.Text>
            {syncStatus?.running_sync && <Tag color="processing">同步进行中</Tag>}
            {syncStatus?.last_sync_status && (
              <Tag color={syncStatus.last_sync_status === 'success' ? 'success' : 'default'}>
                上次：{syncStatus.last_sync_status}
              </Tag>
            )}
            {syncStatus?.last_sync_at && (
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                {syncStatus.last_sync_at.replace('T', ' ').slice(0, 19)} UTC
              </Typography.Text>
            )}
          </Space>
          {syncStatus?.last_sync_error ? (
            <Typography.Text type="danger" style={{ fontSize: 12 }}>
              {syncStatus.last_sync_error.slice(0, 300)}
            </Typography.Text>
          ) : null}
        </Space>
      </ContentCard>

      {info && (
        <ContentCard title={info.bucket}>
          <Space wrap>
            {info.root_prefixes.map((z) => (
              <Tooltip key={z.prefix} title={z.hint}>
                <Button onClick={() => loadList(z.prefix)}>
                  {z.label}
                  <Typography.Text type="secondary" style={{ fontSize: 11, marginLeft: 6 }}>
                    {z.prefix}
                  </Typography.Text>
                </Button>
              </Tooltip>
            ))}
          </Space>
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
            <Button icon={<FolderAddOutlined />} onClick={() => setMkdirOpen(true)}>
              新建目录
            </Button>
            <Upload customRequest={onUpload} showUploadList={false} multiple>
              <Button type="primary" icon={<UploadOutlined />}>
                上传文件
              </Button>
            </Upload>
          </Space>
        }
      >
        <Breadcrumb items={breadcrumbItems()} style={{ marginBottom: 12 }} />
        <Typography.Text type="secondary" style={{ display: 'block', marginBottom: 12, fontSize: 12 }}>
          当前路径：<Typography.Text code>{prefix || '/'}</Typography.Text>
          {prefix.startsWith('rosbags/') && (
            <span style={{ marginLeft: 8 }}>
              · 在 rosbags/ 根目录上传 .bag 会自动创建同名子目录
            </span>
          )}
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
              render: (v: string | null) => (v ? v.replace('T', ' ').slice(0, 19) : '—'),
            },
            {
              title: '操作',
              width: 220,
              render: (_, r) => (
                <Space size={4}>
                  {r.type === 'file' && (
                    <Button type="link" size="small" icon={<DownloadOutlined />} onClick={() => onDownload(r.key)}>
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

      <Modal
        title="新建目录"
        open={mkdirOpen}
        onOk={onMkdir}
        onCancel={() => setMkdirOpen(false)}
        okText="创建"
      >
        <Input
          placeholder="目录名称"
          value={newDirName}
          onChange={(e) => setNewDirName(e.target.value)}
          onPressEnter={onMkdir}
          addonBefore={prefix || '/'}
        />
      </Modal>

      <Modal
        title="Bag 管线状态"
        open={pipelineOpen}
        onCancel={() => {
          setPipelineOpen(false)
          setPipelineKey('')
        }}
        footer={
          <Space>
            <Button
              icon={<ReloadOutlined />}
              loading={pipelineLoading}
              onClick={() => pipelineKey && loadPipeline(pipelineKey, true)}
            >
              刷新
            </Button>
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
        width={600}
      >
        <Spin spinning={pipelineLoading} tip="正在查询 MaxCompute 管线状态（首次约 30–60 秒）…">
          <Space direction="vertical" style={{ width: '100%', minHeight: 120 }} size={12}>
            <Typography.Text code>{pipeline?.oss_key ?? pipelineKey}</Typography.Text>
            {pipelineLoading && !pipeline && (
              <>
                <Tag color="processing">查询中</Tag>
                <Skeleton active paragraph={{ rows: 4 }} />
              </>
            )}
            {pipeline && (
              <>
                <Space wrap>
                  <Tag color={BAG_PIPELINE_STATUS[pipeline.pipeline_status].color}>
                    {BAG_PIPELINE_STATUS[pipeline.pipeline_status].text}
                  </Tag>
                  {pipeline.run_status && (
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      run 状态：{pipeline.run_status}
                    </Typography.Text>
                  )}
                  {pipeline.ds && (
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      ds={pipeline.ds}
                    </Typography.Text>
                  )}
                  {pipeline.is_active_run === false && (
                    <Tag color="orange">非当前 active run</Tag>
                  )}
                </Space>
                {pipeline.message && (
                  <Alert type="info" showIcon message={pipeline.message} />
                )}
                {pipeline.pipeline_steps?.length ? (
                  <UploadPipelineProgress
                    steps={pipeline.pipeline_steps}
                    clipId={pipeline.clip_id ?? undefined}
                    runId={pipeline.run_id ?? undefined}
                  />
                ) : (
                  <Typography.Text type="secondary">暂无步骤数据</Typography.Text>
                )}
                {pipelineLoading && (
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    后台刷新中…
                  </Typography.Text>
                )}
                {pipeline.pipeline_status === 'running' && (
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    每 8 秒自动刷新
                  </Typography.Text>
                )}
              </>
            )}
            {!pipeline && !pipelineLoading && (
              <Typography.Text type="secondary">加载失败，请点刷新重试</Typography.Text>
            )}
          </Space>
        </Spin>
      </Modal>
    </PageStack>
  )
}
