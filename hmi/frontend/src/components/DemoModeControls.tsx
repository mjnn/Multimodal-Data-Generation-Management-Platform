import { ReloadOutlined } from '@ant-design/icons'
import { Button, Modal, Space, Switch, Tooltip, Typography, message } from 'antd'
import { useState } from 'react'
import { api } from '../api'
import { useDemoMode } from '../context/DemoModeContext'

type Props = {
  collapsed?: boolean
}

export function DemoModeControls({ collapsed = false }: Props) {
  const { demoMode, setDemoMode, bumpDemoDataVersion } = useDemoMode()
  const [resetting, setResetting] = useState(false)

  const handleReset = () => {
    Modal.confirm({
      title: '重置演示数据？',
      content: '将清除现有演示 Clip 并重新生成全套 mock 数据（覆盖 AI 打标各场景），演示校核与数据集流程不受影响。',
      okText: '确认重置',
      cancelText: '取消',
      okButtonProps: { danger: true },
      onOk: async () => {
        setResetting(true)
        try {
          await api.resetDemoData()
          message.success('演示数据已重置')
          bumpDemoDataVersion()
        } catch (e: unknown) {
          const msg = e instanceof Error ? e.message : '重置演示数据失败'
          message.error(msg)
          throw e
        } finally {
          setResetting(false)
        }
      },
    })
  }

  if (collapsed) {
    return (
      <div className="app-shell__demo-controls app-shell__demo-controls--collapsed">
        <Tooltip title={demoMode ? '演示模式：开' : '演示模式：关'} placement="right">
          <Switch
            size="small"
            checked={demoMode}
            onChange={setDemoMode}
            aria-label="演示模式"
            data-testid="demo-mode-switch"
          />
        </Tooltip>
        {demoMode ? (
          <Tooltip title="重置演示数据" placement="right">
            <Button
              type="text"
              size="small"
              icon={<ReloadOutlined />}
              loading={resetting}
              onClick={handleReset}
              aria-label="重置演示数据"
              data-testid="demo-reset-button"
            />
          </Tooltip>
        ) : null}
      </div>
    )
  }

  return (
    <div className="app-shell__demo-controls">
      <Space direction="vertical" size={8} style={{ width: '100%' }}>
        <Space size={8} wrap style={{ width: '100%' }}>
          <Switch
            checked={demoMode}
            onChange={setDemoMode}
            size="small"
            data-testid="demo-mode-switch"
          />
          <Typography.Text className="app-shell__demo-label">演示模式</Typography.Text>
          {demoMode ? (
            <Typography.Text type="secondary" className="app-shell__demo-hint">
              仅演示数据
            </Typography.Text>
          ) : (
            <Typography.Text type="secondary" className="app-shell__demo-hint">
              仅真实数据
            </Typography.Text>
          )}
        </Space>
        {demoMode ? (
          <Button
            size="small"
            icon={<ReloadOutlined />}
            loading={resetting}
            onClick={handleReset}
            block
            data-testid="demo-reset-button"
          >
            重置演示数据
          </Button>
        ) : null}
      </Space>
    </div>
  )
}
