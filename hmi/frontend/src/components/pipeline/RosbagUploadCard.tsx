import { DeleteOutlined, InboxOutlined, PlayCircleOutlined } from '@ant-design/icons'
import { Button, Descriptions, List, Modal, Progress, Space, Typography, Upload, message } from 'antd'
import type { UploadProps } from 'antd'
import { useCallback, useMemo, useRef, useState } from 'react'
import { api } from '../../api'
import type { PipelineRunSettings, TaxonomyArchiveReason } from '../../api/types'
import { useDataSourceMode } from '../../context/DataSourceModeContext'
import { apiErrorMessage } from '../../utils/apiError'
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
  return backendLabel || '默认（仓库 taxonomy）'
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

type StagedBag = {
  uid: string
  file: File
}

function isBagFile(name: string): boolean {
  return name.toLowerCase().endsWith('.bag')
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
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
  const [uploadProgress, setUploadProgress] = useState<UploadProgressState | null>(null)
  const [paramsOpen, setParamsOpen] = useState(false)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [settingsPreview, setSettingsPreview] = useState<{
    settings: PipelineRunSettings
    taxonomyVersions: TaxonomyVersionOption[]
  } | null>(null)
  const warnedInvalidRef = useRef(false)

  const stagingTotalBytes = useMemo(
    () => staging.reduce((sum, item) => sum + item.file.size, 0),
    [staging],
  )

  const addToStaging = useCallback((file: File, uid: string) => {
    setStaging((prev) => {
      const dup = prev.some((s) => s.file.name === file.name && s.file.size === file.size)
      if (dup) {
        message.info(`${file.name} 已在暂存区`)
        return prev
      }
      return [...prev, { uid, file }]
    })
  }, [])

  const removeStaged = useCallback((uid: string) => {
    setStaging((prev) => prev.filter((s) => s.uid !== uid))
  }, [])

  const clearStaging = useCallback(() => {
    setStaging([])
  }, [])

  const beforeUpload: UploadProps['beforeUpload'] = (file, fileList) => {
    if (!isBagFile(file.name)) {
      if (!warnedInvalidRef.current) {
        const invalidCount = fileList.filter((item) => !isBagFile(item.name)).length
        if (invalidCount > 0) {
          message.warning(`已跳过 ${invalidCount} 个非 .bag 文件`)
        }
        warnedInvalidRef.current = true
        window.setTimeout(() => {
          warnedInvalidRef.current = false
        }, 0)
      }
      return Upload.LIST_IGNORE
    }
    addToStaging(file as File, file.uid)
    return false
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
      const result = await api.createPipelineExecution(staging.map((s) => s.file), {
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

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Upload.Dragger
        accept=".bag"
        multiple
        showUploadList={false}
        beforeUpload={beforeUpload}
        disabled={uploading}
      >
        <p className="ant-upload-drag-icon">
          <InboxOutlined />
        </p>
        <Typography.Text strong>添加 ROSbag 到暂存区</Typography.Text>
        <Typography.Paragraph type="secondary" style={{ marginBottom: 0, fontSize: 12 }}>
          选择或拖入多个 .bag，先进入下方暂存列表；确认执行参数后才会写入 oss/rosbags/ 并加入 SDK 执行队列
        </Typography.Paragraph>
      </Upload.Dragger>

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
                      disabled={uploading}
                      onClick={() => removeStaged(item.uid)}
                    >
                      移除
                    </Button>,
                  ]}
                >
                  <List.Item.Meta title={item.file.name} description={formatBytes(item.file.size)} />
                </List.Item>
              )}
            />
          </div>
          <Space wrap>
            <Button onClick={clearStaging} disabled={uploading}>
              清空暂存
            </Button>
            <Button
              type="primary"
              icon={<PlayCircleOutlined />}
              loading={uploading}
              disabled={!localOnly}
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
          暂存区为空，请先添加 .bag 文件
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
              {staging.length === 1 ? ` · ${staging[0]?.file.name}` : ` · 共 ${staging.length} 个文件`}
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
