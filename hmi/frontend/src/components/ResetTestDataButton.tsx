import { ReloadOutlined } from '@ant-design/icons'
import { Alert, Button, Modal, Progress, Space, Tooltip, Typography, message } from 'antd'
import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { useDataSourceMode } from '../context/DataSourceModeContext'
import { apiErrorMessage } from '../utils/apiError'

type Props = {
  collapsed?: boolean
  block?: boolean
  /** Danger button on OSS page header etc. */
  danger?: boolean
}

export function ResetTestDataButton({ collapsed = false, block = false, danger = false }: Props) {
  const { localMode, bumpDataRevision } = useDataSourceMode()
  const [resetting, setResetting] = useState(false)
  const [progressOpen, setProgressOpen] = useState(false)
  const [percent, setPercent] = useState(0)
  const [statusMessage, setStatusMessage] = useState('准备中…')
  const [progressStatus, setProgressStatus] = useState<'active' | 'success' | 'exception'>('active')
  const pollRef = useRef<number | null>(null)

  const stopPoll = () => {
    if (pollRef.current != null) {
      window.clearInterval(pollRef.current)
      pollRef.current = null
    }
  }

  useEffect(() => () => stopPoll(), [])

  const startProgressPoll = () => {
    stopPoll()
    pollRef.current = window.setInterval(() => {
      void api
        .getResetArtifactsStatus()
        .then((s) => {
          setPercent(s.percent)
          if (s.message) setStatusMessage(s.message)
          if (s.error) {
            setProgressStatus('exception')
            setStatusMessage(s.error)
          } else if (s.ok) {
            setProgressStatus('success')
            setPercent(100)
          }
        })
        .catch(() => {
          /* ignore transient poll errors while POST is in flight */
        })
    }, 600)
  }

  const runReset = async () => {
    setResetting(true)
    setProgressOpen(true)
    setPercent(0)
    setProgressStatus('active')
    setStatusMessage(localMode ? '正在重置本地测试数据…' : '正在清理云端 OSS / MaxCompute…')
    startProgressPoll()
    try {
      const res = await api.resetHmiArtifacts()
      stopPoll()
      setPercent(100)
      setProgressStatus('success')
      setStatusMessage(res.message ?? '测试数据已重置')
      message.success(res.message ?? '测试数据已重置')
      bumpDataRevision()
    } catch (e: unknown) {
      stopPoll()
      setProgressStatus('exception')
      const msg = apiErrorMessage(e, '重置测试数据失败')
      setStatusMessage(msg)
      message.error(msg)
    } finally {
      setResetting(false)
    }
  }

  const handleReset = () => {
    Modal.confirm({
      title: '重置测试数据？',
      content: (
        <>
          <p>将恢复到 baseline 初始状态（需 admin 权限，仅测试模式可用）：</p>
          <ul style={{ marginBottom: 12, paddingLeft: 20 }}>
            <li>清空管线执行队列（含云端批次记录）</li>
            <li>清空人工校核、派单任务、数据集快照与审计日志</li>
            <li>删除除 admin 以外的所有用户</li>
            <li>
              标签树仅保留已发布版本 <strong>label_tree_baseline</strong>
              （IVI / NVH / 问题音频草稿树会按种子重建，不发布 audio_nvh-v2）
            </li>
            <li data-testid="reset-confirm-datatypes">
              DataType 仅保留内置：<code>oms_cabin</code>、
              <code>ivi_ui_stub</code>、<code>audio_array_spec</code>、
              <code>audio_defect</code>
              （用户新建类型删除，配方恢复为种子）
            </li>
            <li data-testid="reset-confirm-lake">
              源湖：清空 OSS 前缀 <code>sources/</code>、<code>lake_images/</code>、
              <code>platform_runs/</code> 及源湖登记
            </li>
            <li data-testid="reset-confirm-products">
              产物预览：清空管线产物血缘（<code>platform_product</code>）与本机
              <code>work/sdk_runs</code>、<code>artifacts</code>
            </li>
            {localMode ? (
              <li>
                本地：清空 SDK 管线（<code>hmi.db</code>、上传 rosbag、
                <code>oss/rosbags|clips|pipeline</code>、artifacts）
              </li>
            ) : (
              <li>
                云端：清空 OSS（rosbags / clips / pipeline / datasets / reviews / config /
                sources / lake_images / platform_runs）与 MaxCompute
                表数据（aig_sdk__* / aig_rosbag__*），并重新导出 baseline 标签树
              </li>
            )}
          </ul>
          {!localMode ? (
            <Alert
              type="warning"
              showIcon
              message="云端清理可能需要数分钟"
              description="确认后将显示进度条；请保持页面打开，勿重复点击。"
            />
          ) : null}
        </>
      ),
      okText: '确认重置',
      cancelText: '取消',
      okButtonProps: { danger: true },
      width: 520,
      onOk: () => {
        void runReset()
      },
    })
  }

  const progressFooter =
    progressStatus === 'active' ? null : (
      <Button type="primary" onClick={() => setProgressOpen(false)}>
        关闭
      </Button>
    )

  return (
    <>
      {collapsed ? (
        <Tooltip title="重置测试数据" placement="right">
          <Button
            type="text"
            size="small"
            danger={danger}
            icon={<ReloadOutlined />}
            loading={resetting}
            onClick={handleReset}
            aria-label="重置测试数据"
            data-testid="hmi-reset-button"
          />
        </Tooltip>
      ) : (
        <Button
          size="small"
          danger={danger || undefined}
          icon={<ReloadOutlined />}
          loading={resetting}
          onClick={handleReset}
          block={block}
          data-testid="hmi-reset-button"
        >
          重置测试数据
        </Button>
      )}

      <Modal
        title="重置测试数据进度"
        open={progressOpen}
        closable={progressStatus !== 'active'}
        maskClosable={progressStatus !== 'active'}
        keyboard={progressStatus !== 'active'}
        footer={progressFooter}
        onCancel={() => {
          if (progressStatus !== 'active') setProgressOpen(false)
        }}
        width={480}
        destroyOnHidden
      >
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Progress
            percent={percent}
            status={progressStatus}
            strokeColor={progressStatus === 'exception' ? undefined : { from: '#1677ff', to: '#52c41a' }}
          />
          <Typography.Text type={progressStatus === 'exception' ? 'danger' : 'secondary'}>
            {statusMessage}
          </Typography.Text>
        </Space>
      </Modal>
    </>
  )
}
