import { UndoOutlined } from '@ant-design/icons'
import { Button, Form, Input, Modal, Space, Typography } from 'antd'
import { useEffect } from 'react'
import type { OmniLabelPromptFieldMeta } from '../../api/types'

type Props = {
  open: boolean
  fields: OmniLabelPromptFieldMeta[]
  defaults: Record<string, string>
  value: Record<string, string>
  onCancel: () => void
  onOk: (next: Record<string, string>) => void
}

export function OmniLabelPromptSettingsModal({
  open,
  fields,
  defaults,
  value,
  onCancel,
  onOk,
}: Props) {
  const [form] = Form.useForm<Record<string, string>>()

  useEffect(() => {
    if (!open) return
    const merged = { ...defaults, ...value }
    form.setFieldsValue(merged)
  }, [open, defaults, value, form])

  const resetDefaults = () => {
    form.setFieldsValue(defaults)
  }

  const submit = async () => {
    const vals = await form.validateFields()
    onOk(vals as Record<string, string>)
  }

  return (
    <Modal
      title="结构化提示词设置"
      open={open}
      onCancel={onCancel}
      onOk={() => void submit()}
      width={720}
      destroyOnClose
      footer={
        <Space>
          <Button icon={<UndoOutlined />} onClick={resetDefaults}>
            恢复 SDK 默认
          </Button>
          <Button onClick={onCancel}>取消</Button>
          <Button type="primary" onClick={() => void submit()}>
            确定
          </Button>
        </Space>
      }
    >
      <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
        以下字段对应 Omni 打标提示词脚手架中可调的文案（角色、规则、用户任务句等）。taxonomy
        标签列表仍由「标签树版本」动态生成。保存执行参数后，本地 SDK 轮询将使用合并后的提示词。
      </Typography.Paragraph>
      <Form form={form} layout="vertical">
        {fields.map((f) => (
          <Form.Item
            key={f.key}
            name={f.key}
            label={f.label}
            extra={f.description}
            rules={[{ required: true, message: '请填写内容' }]}
          >
            {f.multiline ? (
              <Input.TextArea rows={f.key === 'json_format_hint' ? 8 : 5} />
            ) : (
              <Input />
            )}
          </Form.Item>
        ))}
      </Form>
    </Modal>
  )
}
