/**
 * 管线管理 · Rosbag 暂存与批量执行入口。
 *
 * - 多选 .bag / 「选择采集文件夹」/ 拖入目录树 → 暂存区
 * - 文件夹场景会递归收集 .bag，列表展示相对路径
 * - 确认参数后 multipart 上传；File.name 带相对路径，后端按内容哈希分目录落盘
 */
import { DeleteOutlined, FolderOpenOutlined, InboxOutlined, PlayCircleOutlined } from '@ant-design/icons'
import { Button, Descriptions, List, Modal, Progress, Space, Typography, Upload, message } from 'antd'
import type { UploadProps } from 'antd'
import { useCallback, useMemo, useRef, useState, type DragEvent } from 'react'
import { api } from '../../api'
import type { PipelineRunSettings, TaxonomyArchiveReason } from '../../api/types'
import { useDataSourceMode } from '../../context/DataSourceModeContext'
import { apiErrorMessage } from '../../utils/apiError'
import {
  collectBagsFromDataTransfer,
  fileForUpload,
  isBagFileName,
  toStagedBag,
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
  percent: number
  loaded: number
  total: number
}

export function RosbagUploadCard({ onUploaded }: Props) {
  const { bumpDataRevision, dataSource } = useDataSourceMode()
  const [staging, setStaging] = useState<StagedBag[]>([])
  const [uploading, setUploading] = useState(false)
  const [parsingFolders, setParsingFolders] = useState(false)
  const [uploadProgress, setUploadProgress] = useState<UploadProgressState | null>(null)
  const [paramsOpen, setParamsOpen] = useState(false)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [settingsPreview, setSettingsPreview] = useState<{
    settings: PipelineRunSettings
    taxonomyVersions: TaxonomyVersionOption[]
  } | null>(null)
  const fileBatchRef = useRef<{ total: number; bags: number; done: number } | null>(null)
  /** Skip antd beforeUpload when we already handled a folder drop via FileSystemEntry walk. */
  const skipAntdDropBatchRef = useRef(false)

  const stagingTotalBytes = useMemo(
    () => staging.reduce((sum, item) => sum + item.file.size, 0),
    [staging],
  )

  const mergeIntoStaging = useCallback((items: StagedBagFile[]) => {
    if (!items.length) {
      message.warning('未找到 .bag 文件（请选择含 bag 的采集文件夹或其时间戳子目录）')
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
        next.push({
          uid: `${key}::${item.file.lastModified}::${Math.random().toString(36).slice(2, 8)}`,
          file: item.file,
          relativePath: item.relativePath,
        })
        added += 1
      }
      if (added > 0) {
        message.success(`已加入暂存 ${added} 个 .bag${skipped ? `（跳过重复 ${skipped}）` : ''}`)
      } else if (skipped > 0) {
        message.info('所选 bag 均已在暂存区')
      }
      return next
    })
  }, [])

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
    if (isBagFileName(file.name)) {
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
          },
        ]
      })
    }
    if (batch.done === batch.total) {
      if (batch.bags > 0) {
        message.success(`已解析 ${batch.bags} 个 .bag（共扫描 ${batch.total} 个文件）`)
      } else {
        message.warning('未找到 .bag 文件（请选择含 bag 的采集文件夹或其时间戳子目录）')
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
    void collectBagsFromDataTransfer(dt)
      .then((bags) => mergeIntoStaging(bags))
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
      setParamsOpen(true)
    } catch (e: unknown) {
      message.error(apiErrorMessage(e, '加载执行参数失败'))
    }
  }

  const onConfirmParams = () => {
    setParamsOpen(false)
    setConfirmOpen(true)
  }

  const executePipeline = async () => {
    if (!staging.length || uploading) return
    setUploading(true)
    const expectedTotal = stagingTotalBytes
    setUploadProgress({ percent: 0, loaded: 0, total: expectedTotal })
    try {
      const result = await api.createPipelineExecution(staging.map((s) => fileForUpload(s)), {
        onUploadProgress: ({ loaded, total, percent }) => {
          setUploadProgress({
            percent,
            loaded,
            total: total > 0 ? total : expectedTotal,
          })
        },
      })
      message.success(
        `已加入执行队列：${result.label}，${result.clips.length} 个 clip（run ${result.run_id.slice(0, 8)}…）`,
      )
      setStaging([])
      setConfirmOpen(false)
      bumpDataRevision()
      onUploaded?.()
    } catch (e: unknown) {
      message.error(apiErrorMessage(e, '加入执行队列失败'))
    } finally {
      setUploading(false)
      setUploadProgress(null)
    }
  }

  const localOnly = dataSource === 'local'
  const busy = uploading || parsingFolders

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <div onDragOver={onZoneDragOver} onDrop={onZoneDrop}>
        <Upload.Dragger
          accept=".bag"
          multiple
          showUploadList={false}
          beforeUpload={beforeUpload}
          disabled={busy}
        >
          <p className="ant-upload-drag-icon">
            <InboxOutlined />
          </p>
          <Typography.Text strong>添加 ROSbag 到暂存区</Typography.Text>
          <Typography.Paragraph type="secondary" style={{ marginBottom: 0, fontSize: 12 }}>
            可多选 .bag，或拖入采集根目录 / 多个时间戳文件夹（自动递归找 .bag）。同名不同内容按内容哈希分目录保存。
          </Typography.Paragraph>
        </Upload.Dragger>
      </div>

      <Upload directory multiple showUploadList={false} beforeUpload={beforeUpload} disabled={busy}>
        <Button icon={<FolderOpenOutlined />} loading={parsingFolders} disabled={busy}>
          选择采集文件夹（递归解析 .bag）
        </Button>
      </Upload>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        例如选择 <code>0804caiji</code>
        ：会解析其下每个时间戳子目录中的 bag。可多次点选以加入多个文件夹；也可一次拖入多个文件夹。
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
                    title={item.relativePath}
                    description={formatBytes(item.file.size)}
                  />
                </List.Item>
              )}
            />
          </div>
          <Space wrap>
            <Button onClick={clearStaging} disabled={busy}>
              清空暂存
            </Button>
            <Button
              type="primary"
              icon={<PlayCircleOutlined />}
              loading={uploading}
              disabled={!localOnly || parsingFolders}
              onClick={() => void openParamsModal()}
            >
              确认执行管线
            </Button>
          </Space>
          {!localOnly ? (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              批量执行队列仅在本地数据源模式下可用
            </Typography.Text>
          ) : null}
        </>
      ) : (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          暂存区为空，请添加 .bag 或选择采集文件夹
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
          将使用当前「执行参数」卡片中的配置；如需修改请先保存后再执行。
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
          本批 <strong>{staging.length}</strong> 个 rosbag 将共用一次 run_id，并按 clip 并发执行 SDK 步骤。
        </Typography.Paragraph>
      </Modal>

      <Modal
        title="二次确认"
        open={confirmOpen}
        onCancel={() => {
          if (!uploading) setConfirmOpen(false)
        }}
        onOk={() => executePipeline()}
        okText="开始执行"
        cancelText="取消"
        confirmLoading={uploading && (uploadProgress?.percent ?? 0) >= 100}
        okButtonProps={{ disabled: uploading }}
        cancelButtonProps={{ disabled: uploading }}
        closable={!uploading}
        maskClosable={!uploading}
      >
        {uploading && uploadProgress ? (
          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            <Typography.Paragraph style={{ marginBottom: 0 }}>
              {uploadProgress.percent < 100
                ? `正在上传 ${staging.length} 个 rosbag 到服务器…`
                : '上传已完成，正在写入磁盘并计算校验（大文件可能还需数分钟，请耐心等待）…'}
            </Typography.Paragraph>
            <Progress
              percent={uploadProgress.percent}
              status={uploadProgress.percent >= 100 ? 'active' : 'normal'}
            />
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {formatBytes(uploadProgress.loaded)} / {formatBytes(uploadProgress.total)}
              {staging.length === 1
                ? ` · ${staging[0]?.relativePath}`
                : ` · 共 ${staging.length} 个文件`}
            </Typography.Text>
          </Space>
        ) : (
          <Typography.Paragraph>
            确认将暂存区 <strong>{staging.length}</strong> 个 rosbag 加入管线执行队列？写入后将由本地 SDK
            轮询处理。
            {stagingTotalBytes > 0 ? (
              <>
                {' '}
                本批合计约 <strong>{formatBytes(stagingTotalBytes)}</strong>，上传与校验期间请勿关闭页面。
              </>
            ) : null}
          </Typography.Paragraph>
        )}
      </Modal>
    </Space>
  )
}
