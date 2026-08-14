/**
 * 管线管理 · 源数据暂存与批量执行入口。
 *
 * - 多选 .bag / 视频 / 音频 / 文本；或「选择采集文件夹」/ 拖入目录树 → 暂存区
 * - 本地：bag 各成 clip；同批非 bag 媒体合并为一个原始媒体 clip（CapabilityPlanner 按模态跳过阶段）
 * - 云端：目前仅 .bag；原始媒体请切 local
 */
import { CloudUploadOutlined, DeleteOutlined, FolderOpenOutlined, InboxOutlined, PlayCircleOutlined } from '@ant-design/icons'
import { Button, Descriptions, List, Modal, Progress, Space, Tag, Typography, Upload, message } from 'antd'
import type { UploadProps } from 'antd'
import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent } from 'react'
import { api } from '../../api'
import type { PipelineRunSettings, TaxonomyArchiveReason } from '../../api/types'
import { useDataSourceMode } from '../../context/DataSourceModeContext'
import { apiErrorMessage } from '../../utils/apiError'
import {
  classifySourceFileName,
  collectSourcesFromDataTransfer,
  fileForUpload,
  isPipelineSourceFileName,
  modalityLabel,
  toStagedBag,
  type SourceModality,
  type StagedBagFile,
} from '../../utils/rosbagStaging'
import { formatTaxonomyVersionLabel } from '../../utils/taxonomyDisplay'

type TaxonomyVersionOption = {
  id: string
  version_code: string
  status: string
  archive_reason?: TaxonomyArchiveReason | null
}

const TAXONOMY_UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i

function resolveTaxonomyConfirmLabel(
  settings: PipelineRunSettings,
  versions: TaxonomyVersionOption[],
): string {
  const tid = settings.taxonomy_version_id
  if (tid) {
    const match = versions.find((v) => v.id === tid)
    if (match) return formatTaxonomyVersionLabel(match)
  }
  const backendLabel = settings.taxonomy_version_label?.trim()
  if (backendLabel && !TAXONOMY_UUID_RE.test(backendLabel)) {
    return backendLabel
  }
  const published = versions.find((v) => v.status === 'published')
  if (published) {
    return `默认（${formatTaxonomyVersionLabel(published)}）`
  }
  return backendLabel || '默认（仓库标签树）'
}

function settingsSummaryItems(
  settings: PipelineRunSettings,
  taxonomyVersions: TaxonomyVersionOption[],
) {
  const bboxLabel = settings.bbox_enabled
    ? `${settings.bbox_detector || 'opencv'} + jsonl`
    : '关闭'
  return [
    { key: 'omni', label: '打标模型', children: settings.omni_model ?? 'default' },
    { key: 'embed', label: '向量模型', children: settings.embedding_model ?? 'default' },
    {
      key: 'taxonomy',
      label: '标签树',
      children: resolveTaxonomyConfirmLabel(settings, taxonomyVersions),
    },
    { key: 'fps', label: '抽样 fps', children: String(settings.sample_fps ?? '—') },
    {
      key: 'clip_sec',
      label: 'Clip 时长',
      children: `${settings.min_sec ?? '—'} ~ ${settings.max_sec ?? '—'} 秒`,
    },
    { key: 'max_clips', label: '每 bag 最大 clip', children: String(settings.max_clips ?? '—') },
    {
      key: 'sdk_parallel',
      label: 'SDK 并发',
      children: String(settings.sdk_parallel ?? 1),
    },
    { key: 'bbox', label: 'BBox 检测', children: bboxLabel },
  ]
}

type Props = {
  onUploaded?: () => void
}

type StagedBag = StagedBagFile & { uid: string }

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}

function stagingKey(item: Pick<StagedBag, 'relativePath' | 'file'>): string {
  return `${item.relativePath}::${item.file.size}`
}

function dataTransferHasDirectory(dt: DataTransfer | null): boolean {
  if (!dt?.items?.length) return false
  return Array.from(dt.items).some((item) => Boolean(item.webkitGetAsEntry?.()?.isDirectory))
}

type UploadProgressState = {
  /** upload = browser→HMI; server = OSS put + DataWorks trigger */
  phase: 'upload' | 'server'
  /** Overall 0–100 for the combined bar */
  percent: number
  loaded: number
  total: number
  detail?: string
}

export function RosbagUploadCard({ onUploaded }: Props) {
  const { bumpDataRevision, dataSource } = useDataSourceMode()
  const [staging, setStaging] = useState<StagedBag[]>([])
  const [uploading, setUploading] = useState(false)
  const [parsingFolders, setParsingFolders] = useState(false)
  const [uploadProgress, setUploadProgress] = useState<UploadProgressState | null>(null)
  const [paramsOpen, setParamsOpen] = useState(false)
  const [confirmOpen, setConfirmOpen] = useState(false)
  /** Cloud confirm: trigger OpenAPI vs OSS-only for periodic DW schedule */
  const [confirmMode, setConfirmMode] = useState<'trigger' | 'upload_only'>('trigger')
  const [settingsPreview, setSettingsPreview] = useState<{
    settings: PipelineRunSettings
    taxonomyVersions: TaxonomyVersionOption[]
  } | null>(null)
  const fileBatchRef = useRef<{ total: number; bags: number; done: number } | null>(null)
  /** Skip antd beforeUpload when we already handled a folder drop via FileSystemEntry walk. */
  const skipAntdDropBatchRef = useRef(false)
  const serverPhaseStartedRef = useRef(false)

  const stagingTotalBytes = useMemo(
    () => staging.reduce((sum, item) => sum + item.file.size, 0),
    [staging],
  )

  // Creep overall percent during server phase so「校验/触发」不是卡在 100% 无反馈
  useEffect(() => {
    if (!uploading || uploadProgress?.phase !== 'server') return
    const t = window.setInterval(() => {
      setUploadProgress((prev) => {
        if (!prev || prev.phase !== 'server') return prev
        if (prev.percent >= 95) return prev
        return { ...prev, percent: Math.min(95, prev.percent + 1) }
      })
    }, 700)
    return () => window.clearInterval(t)
  }, [uploading, uploadProgress?.phase])

  const mergeIntoStaging = useCallback((items: StagedBagFile[]) => {
    if (!items.length) {
      message.warning('未找到可上传源文件（.bag / 视频 / 音频 / 文本）')
      return
    }
    setStaging((prev) => {
      const seen = new Set(prev.map((s) => stagingKey(s)))
      const next = [...prev]
      let added = 0
      let skipped = 0
      for (const item of items) {
        const key = stagingKey(item)
        if (seen.has(key)) {
          skipped += 1
          continue
        }
        seen.add(key)
        const modality = item.modality || classifySourceFileName(item.relativePath) || undefined
        next.push({
          uid: `${key}::${item.file.lastModified}::${Math.random().toString(36).slice(2, 8)}`,
          file: item.file,
          relativePath: item.relativePath,
          modality,
        })
        added += 1
      }
      if (added > 0) {
        message.success(`已加入暂存 ${added} 个文件${skipped ? `（跳过重复 ${skipped}）` : ''}`)
      } else if (skipped > 0) {
        message.info('所选文件均已在暂存区')
      }
      return next
    })
  }, [])

  const stagingModalitySummary = useMemo(() => {
    const counts: Partial<Record<SourceModality, number>> = {}
    for (const item of staging) {
      const m = item.modality || classifySourceFileName(item.relativePath)
      if (!m) continue
      counts[m] = (counts[m] || 0) + 1
    }
    return counts
  }, [staging])

  const removeStaged = useCallback((uid: string) => {
    setStaging((prev) => prev.filter((s) => s.uid !== uid))
  }, [])

  const clearStaging = useCallback(() => {
    setStaging([])
  }, [])

  const beforeUpload: UploadProps['beforeUpload'] = (file, fileList) => {
    if (skipAntdDropBatchRef.current) {
      if (fileList.indexOf(file) === fileList.length - 1) {
        skipAntdDropBatchRef.current = false
      }
      return Upload.LIST_IGNORE
    }
    const total = fileList.length
    if (!fileBatchRef.current || fileBatchRef.current.total !== total) {
      fileBatchRef.current = { total, bags: 0, done: 0 }
    }
    const batch = fileBatchRef.current
    batch.done += 1
    if (isPipelineSourceFileName(file.name)) {
      batch.bags += 1
      const staged = toStagedBag(file as File)
      setStaging((prev) => {
        if (prev.some((s) => stagingKey(s) === stagingKey(staged))) return prev
        return [
          ...prev,
          {
            uid: `${stagingKey(staged)}::${file.uid}`,
            file: staged.file,
            relativePath: staged.relativePath,
            modality: staged.modality,
          },
        ]
      })
    }
    if (batch.done === batch.total) {
      if (batch.bags > 0) {
        message.success(`已解析 ${batch.bags} 个源文件（共扫描 ${batch.total} 个文件）`)
      } else {
        message.warning('未找到可上传源文件（.bag / 视频 / 音频 / 文本）')
      }
      fileBatchRef.current = null
    }
    return Upload.LIST_IGNORE
  }

  const onZoneDragOver = (event: DragEvent) => {
    if (dataTransferHasDirectory(event.dataTransfer)) {
      event.preventDefault()
      event.stopPropagation()
    }
  }

  const onZoneDrop = (event: DragEvent) => {
    if (!dataTransferHasDirectory(event.dataTransfer)) return
    event.preventDefault()
    event.stopPropagation()
    skipAntdDropBatchRef.current = true
    const dt = event.dataTransfer
    setParsingFolders(true)
    void collectSourcesFromDataTransfer(dt)
      .then((items) => mergeIntoStaging(items))
      .catch(() => {
        skipAntdDropBatchRef.current = false
        message.error('解析拖入文件夹失败')
      })
      .finally(() => setParsingFolders(false))
  }

  const openParamsModal = async () => {
    if (!staging.length || uploading) return
    try {
      const res = await api.getPipelineSettings()
      setSettingsPreview({
        settings: res.settings,
        taxonomyVersions: res.options.taxonomy_versions,
      })
      setConfirmMode('trigger')
      setParamsOpen(true)
    } catch (e: unknown) {
      message.error(apiErrorMessage(e, '加载执行参数失败'))
    }
  }

  const openUploadOnlyConfirm = () => {
    if (!staging.length || uploading) return
    setConfirmMode('upload_only')
    setConfirmOpen(true)
  }

  const onConfirmParams = () => {
    setParamsOpen(false)
    setConfirmMode('trigger')
    setConfirmOpen(true)
  }

  const executePipeline = async () => {
    if (!staging.length || uploading) return
    const uploadOnly = dataSource === 'cloud' && confirmMode === 'upload_only'
    setUploading(true)
    serverPhaseStartedRef.current = false
    const expectedTotal = stagingTotalBytes
    setUploadProgress({
      phase: 'upload',
      percent: 0,
      loaded: 0,
      total: expectedTotal,
      detail: dataSource === 'cloud' ? '正在上传到 HMI 服务…' : '正在上传到服务器…',
    })
    try {
      const result = await api.createPipelineExecution(staging.map((s) => fileForUpload(s)), {
        trigger: uploadOnly ? false : undefined,
        onUploadProgress: ({ loaded, total, percent }) => {
          const byteTotal = total > 0 ? total : expectedTotal
          if (percent >= 100) {
            if (!serverPhaseStartedRef.current) {
              serverPhaseStartedRef.current = true
              setUploadProgress({
                phase: 'server',
                percent: 72,
                loaded: byteTotal,
                total: byteTotal,
                detail: uploadOnly
                  ? '上传完成：正在写入 OSS（不触发 OpenAPI）…'
                  : dataSource === 'cloud'
                    ? '上传完成：正在写入 OSS 并触发 DataWorks（校验/落盘中）…'
                    : '上传完成：正在写入磁盘并计算校验…',
              })
            }
            return
          }
          const overall = Math.min(70, Math.round(percent * 0.7))
          setUploadProgress({
            phase: 'upload',
            percent: overall,
            loaded,
            total: byteTotal,
            detail: `正在上传 ${formatBytes(loaded)} / ${formatBytes(byteTotal)}`,
          })
        },
      })
      setUploadProgress((prev) =>
        prev
          ? {
              ...prev,
              phase: 'server',
              percent: 100,
              detail: uploadOnly
                ? '已上传到 OSS，等待周期工作流'
                : dataSource === 'cloud'
                  ? '云端管线已触发'
                  : '已加入执行队列',
            }
          : prev,
      )
      const cloudHint =
        dataSource === 'cloud' && result.dag_id ? `，DataWorks Dag ${result.dag_id}` : ''
      message.success(
        uploadOnly
          ? `已上传 ${result.clips.length} 个 bag 到 OSS（${result.label}），等待 DataWorks 周期工作流发现并跑管线`
          : dataSource === 'cloud'
            ? `已上传并触发云端管线：${result.label}，${result.clips.length} 个 bag${cloudHint}`
            : `已加入执行队列：${result.label}，${result.clips.length} 个 clip（run ${result.run_id.slice(0, 8)}…）；Planner 将按模态跳过无关阶段`,
      )
      setStaging([])
      setConfirmOpen(false)
      bumpDataRevision()
      onUploaded?.()
    } catch (e: unknown) {
      message.error(
        apiErrorMessage(
          e,
          uploadOnly
            ? '上传到 OSS 失败'
            : dataSource === 'cloud'
              ? '触发云端管线失败'
              : '加入执行队列失败',
        ),
      )
    } finally {
      setUploading(false)
      setUploadProgress(null)
      serverPhaseStartedRef.current = false
    }
  }

  const busy = uploading || parsingFolders

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <div onDragOver={onZoneDragOver} onDrop={onZoneDrop}>
        <Upload.Dragger
          accept=".bag,.mp4,.webm,.mov,.mkv,.avi,.wav,.mp3,.m4a,.flac,.ogg,.aac,.txt,.json,.md,.csv"
          multiple
          showUploadList={false}
          beforeUpload={beforeUpload}
          disabled={busy}
        >
          <p className="ant-upload-drag-icon">
            <InboxOutlined />
          </p>
          <Typography.Text strong>添加源数据到暂存区</Typography.Text>
          <Typography.Paragraph type="secondary" style={{ marginBottom: 8, fontSize: 12 }}>
            支持 <Tag>Rosbag</Tag>
            <Tag color="blue">视频</Tag>
            <Tag color="green">音频</Tag>
            <Tag color="orange">文本</Tag>
            。本地：已有成片跳过 bag 帧编码（仍抽帧）；无音频跳过 ASR；无视频跳过 bbox/encode。
          </Typography.Paragraph>
          <Typography.Paragraph type="secondary" style={{ marginBottom: 0, fontSize: 12 }}>
            可多选文件，或拖入采集文件夹（递归收集）。同名不同内容按内容哈希分目录保存。
          </Typography.Paragraph>
        </Upload.Dragger>
      </div>

      <Upload directory multiple showUploadList={false} beforeUpload={beforeUpload} disabled={busy}>
        <Button icon={<FolderOpenOutlined />} loading={parsingFolders} disabled={busy}>
          选择采集文件夹（递归解析源文件）
        </Button>
      </Upload>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        例如选择 <code>0804caiji</code>
        ：会解析其下每个时间戳子目录中的 bag / 媒体。云端模式暂仅支持 .bag；原始媒体请切「本地」。
      </Typography.Text>

      {staging.length > 0 ? (
        <>
          <div>
            <Typography.Text strong>暂存区 ({staging.length})</Typography.Text>
            <List
              size="small"
              bordered
              style={{ marginTop: 8, maxHeight: 240, overflow: 'auto' }}
              dataSource={staging}
              renderItem={(item) => (
                <List.Item
                  actions={[
                    <Button
                      key="remove"
                      type="text"
                      size="small"
                      danger
                      icon={<DeleteOutlined />}
                      disabled={busy}
                      onClick={() => removeStaged(item.uid)}
                    >
                      移除
                    </Button>,
                  ]}
                >
                  <List.Item.Meta
                    title={
                      <Space size={8}>
                        <Tag>
                          {modalityLabel(
                            item.modality || classifySourceFileName(item.relativePath) || undefined,
                          )}
                        </Tag>
                        <span>{item.relativePath}</span>
                      </Space>
                    }
                    description={formatBytes(item.file.size)}
                  />
                </List.Item>
              )}
            />
            <Typography.Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0, fontSize: 12 }}>
              本批模态：
              {(['bag', 'video', 'audio', 'text'] as SourceModality[])
                .filter((m) => stagingModalitySummary[m])
                .map((m) => `${modalityLabel(m)}×${stagingModalitySummary[m]}`)
                .join(' · ') || '—'}
            </Typography.Paragraph>
          </div>
          <Space wrap>
            <Button onClick={clearStaging} disabled={busy}>
              清空暂存
            </Button>
            {dataSource === 'cloud' ? (
              <Button
                icon={<CloudUploadOutlined />}
                loading={uploading}
                disabled={parsingFolders}
                onClick={openUploadOnlyConfirm}
              >
                仅上传到 OSS
              </Button>
            ) : null}
            <Button
              type="primary"
              icon={<PlayCircleOutlined />}
              loading={uploading}
              disabled={parsingFolders}
              onClick={() => void openParamsModal()}
            >
              {dataSource === 'cloud' ? '上传并触发云端管线' : '确认执行管线'}
            </Button>
          </Space>
          {dataSource === 'cloud' ? (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              「仅上传」写入 OSS 后由 DataWorks 周期工作流发现并跑管线（不走 OpenAPI）；「上传并触发」会立刻调
              CreateDagTest / 手动业务流程。
            </Typography.Text>
          ) : null}
        </>
      ) : (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          暂存区为空，请添加 .bag / 视频 / 音频 / 文本，或选择采集文件夹
        </Typography.Text>
      )}

      <Modal
        title="执行参数确认"
        open={paramsOpen}
        onCancel={() => setParamsOpen(false)}
        onOk={onConfirmParams}
        okText="下一步"
        cancelText="取消"
        width={520}
      >
        <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
          {dataSource === 'cloud'
            ? '云端执行参数来自服务端 DataWorks 默认模板（.env / dataworks_sdk_pipeline_defaults.yaml）与本次 bag_oss_keys；下方「执行参数」卡片仅影响本地 SDK。'
            : '将使用当前「执行参数」卡片中的配置；如需修改请先保存后再执行。'}
        </Typography.Paragraph>
        {settingsPreview ? (
          <Descriptions
            column={1}
            size="small"
            bordered
            items={settingsSummaryItems(settingsPreview.settings, settingsPreview.taxonomyVersions)}
          />
        ) : null}
        <Typography.Paragraph style={{ marginTop: 12, marginBottom: 0 }}>
          本批 <strong>{staging.length}</strong> 个源文件将共用一次 run_id（每个 .bag 一个
          clip；原始媒体合并为一个 clip），并由 CapabilityPlanner 按模态编排阶段。
        </Typography.Paragraph>
      </Modal>

      <Modal
        title={confirmMode === 'upload_only' ? '确认仅上传' : '二次确认'}
        open={confirmOpen}
        onCancel={() => {
          if (!uploading) setConfirmOpen(false)
        }}
        onOk={() => void executePipeline()}
        okText={confirmMode === 'upload_only' ? '开始上传' : '开始执行'}
        cancelText="取消"
        confirmLoading={uploading && (uploadProgress?.phase === 'server' || (uploadProgress?.percent ?? 0) >= 70)}
        okButtonProps={{ disabled: uploading }}
        cancelButtonProps={{ disabled: uploading }}
        closable={!uploading}
        maskClosable={!uploading}
      >
        {uploading && uploadProgress ? (
          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            <Typography.Paragraph style={{ marginBottom: 0 }}>
              {uploadProgress.detail ||
                (uploadProgress.phase === 'upload'
                  ? `正在上传 ${staging.length} 个 rosbag…`
                  : confirmMode === 'upload_only'
                    ? '上传完成：正在写入 OSS…'
                    : dataSource === 'cloud'
                      ? '上传完成：正在写入 OSS 并触发 DataWorks…'
                      : '上传完成：正在写入磁盘并计算校验…')}
            </Typography.Paragraph>
            <div>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                {uploadProgress.phase === 'upload' ? '1/2 上传到服务' : '2/2 服务端处理'}
              </Typography.Text>
              <Progress
                percent={uploadProgress.percent}
                status={uploadProgress.percent >= 100 ? 'success' : 'active'}
                strokeColor={uploadProgress.phase === 'server' ? { from: '#108ee9', to: '#87d068' } : undefined}
              />
            </div>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {formatBytes(uploadProgress.loaded)} / {formatBytes(uploadProgress.total)}
              {staging.length === 1
                ? ` · ${staging[0]?.relativePath}`
                : ` · 共 ${staging.length} 个文件`}
            </Typography.Text>
          </Space>
        ) : (
          <Typography.Paragraph>
            {confirmMode === 'upload_only' ? (
              <>
                确认将暂存区 <strong>{staging.length}</strong> 个 rosbag 上传到 OSS，
                <strong>不</strong>调用 DataWorks OpenAPI？周期定时工作流发现新 bag 后会自行跑管线。
              </>
            ) : dataSource === 'cloud' ? (
              <>
                确认将暂存区 <strong>{staging.length}</strong> 个 rosbag 上传至 OSS 并触发云端管线？
              </>
            ) : (
              <>
                确认将暂存区 <strong>{staging.length}</strong> 个 rosbag 加入管线执行队列？写入后将由本地 SDK
                轮询处理。
              </>
            )}
            {stagingTotalBytes > 0 ? (
              <>
                {' '}
                本批合计约 <strong>{formatBytes(stagingTotalBytes)}</strong>
                ，上传与服务端处理期间请勿关闭页面。
              </>
            ) : null}
          </Typography.Paragraph>
        )}
      </Modal>
    </Space>
  )
}
