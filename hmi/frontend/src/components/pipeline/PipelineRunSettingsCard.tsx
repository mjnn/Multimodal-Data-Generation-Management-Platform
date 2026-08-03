import { SaveOutlined, SettingOutlined } from '@ant-design/icons'
import { Button, Form, InputNumber, Select, Space, Typography, message } from 'antd'
import { useCallback, useEffect, useState } from 'react'
import { api } from '../../api'
import type { OmniLabelPromptFieldMeta, PipelineRunSettings, TaxonomyArchiveReason } from '../../api/types'
import { apiErrorMessage } from '../../utils/apiError'
import { formatTaxonomyVersionLabel } from '../../utils/taxonomyDisplay'
import { OmniLabelPromptSettingsModal } from './OmniLabelPromptSettingsModal'

export function PipelineRunSettingsCard() {
  const [form] = Form.useForm<PipelineRunSettings>()
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [omniModels, setOmniModels] = useState<string[]>(['default'])
  const [embeddingModels, setEmbeddingModels] = useState<string[]>(['default'])
  const [taxonomyVersions, setTaxonomyVersions] = useState<
    {
      id: string
      version_code: string
      status: string
      archive_reason?: TaxonomyArchiveReason | null
    }[]
  >([])
  const [promptFields, setPromptFields] = useState<OmniLabelPromptFieldMeta[]>([])
  const [promptDefaults, setPromptDefaults] = useState<Record<string, string>>({})
  const [promptModalOpen, setPromptModalOpen] = useState(false)
  const [omniPrompt, setOmniPrompt] = useState<Record<string, string>>({})

  function taxonomyOptionLabel(v: {
    version_code: string
    status: string
    archive_reason?: TaxonomyArchiveReason | null
  }): string {
    return formatTaxonomyVersionLabel(v)
  }

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await api.getPipelineSettings()
      const mergedPrompt = res.settings.omni_label_prompt ?? res.options.omni_label_prompt_defaults ?? {}
      setOmniPrompt(mergedPrompt)
      form.setFieldsValue({ ...res.settings, omni_label_prompt: mergedPrompt })
      setOmniModels(res.options.omni_models)
      setEmbeddingModels(res.options.embedding_models)
      setTaxonomyVersions(res.options.taxonomy_versions)
      setPromptFields(res.options.omni_label_prompt_fields ?? [])
      setPromptDefaults(res.options.omni_label_prompt_defaults ?? mergedPrompt)
    } catch (e: unknown) {
      message.error(apiErrorMessage(e, '加载管线参数失败'))
    } finally {
      setLoading(false)
    }
  }, [form])

  useEffect(() => {
    void load()
  }, [load])

  const save = async () => {
    const values = await form.validateFields()
    setSaving(true)
    try {
      await api.savePipelineSettings({
        ...values,
        omni_label_prompt: omniPrompt,
      })
      message.success('管线执行参数已保存')
      await load()
    } catch (e: unknown) {
      message.error(apiErrorMessage(e, '保存失败'))
    } finally {
      setSaving(false)
    }
  }

  const omniModel = Form.useWatch('omni_model', form)

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        本地 SDK 轮询处理 rosbag 时使用；模型下拉「default」表示跟随环境变量。
      </Typography.Text>
      <Form form={form} layout="vertical" disabled={loading}>
        <Form.Item name="omni_model" label="打标模型 (Omni)">
          <Select options={omniModels.map((m) => ({ value: m, label: m }))} />
        </Form.Item>
        <Form.Item label=" " colon={false}>
          <Button
            icon={<SettingOutlined />}
            disabled={loading || omniModel === undefined}
            onClick={() => setPromptModalOpen(true)}
          >
            结构化提示词设置
          </Button>
          <Typography.Text type="secondary" style={{ marginLeft: 12, fontSize: 12 }}>
            微调 Omni 打标角色、规则与用户任务句（标签列表仍随标签树版本生成）
          </Typography.Text>
        </Form.Item>
        <Form.Item name="embedding_model" label="向量化模型">
          <Select options={embeddingModels.map((m) => ({ value: m, label: m }))} />
        </Form.Item>
        <Form.Item name="taxonomy_version_id" label="标签树版本">
          <Select
            allowClear
            placeholder="默认（仓库标签树或最新发布）"
            options={taxonomyVersions.map((v) => ({
              value: v.id,
              label: taxonomyOptionLabel(v),
            }))}
          />
        </Form.Item>
        <Space wrap size={16} style={{ width: '100%' }}>
          <Form.Item name="sample_fps" label="抽样频率 (fps)">
            <InputNumber min={0.1} max={30} step={0.1} style={{ width: 140 }} />
          </Form.Item>
          <Form.Item name="min_sec" label="Clip 最短 (秒)">
            <InputNumber min={1} max={120} style={{ width: 120 }} />
          </Form.Item>
          <Form.Item name="max_sec" label="Clip 最长 (秒)">
            <InputNumber min={1} max={300} style={{ width: 120 }} />
          </Form.Item>
          <Form.Item name="max_clips" label="每 bag 最大 clip 数">
            <InputNumber min={1} max={50} style={{ width: 120 }} />
          </Form.Item>
          <Form.Item
            name="sdk_parallel"
            label="SDK 并发 clip 数"
            tooltip="同时跑 Omni 打标的 clip 数量；1 为顺序执行。保存后立即生效（若服务器设置了环境变量 HMI_LOCAL_SDK_PARALLEL 则环境变量优先）。"
          >
            <InputNumber min={1} max={8} style={{ width: 120 }} />
          </Form.Item>
        </Space>
      </Form>
      <Button type="primary" icon={<SaveOutlined />} loading={saving} onClick={() => void save()}>
        保存执行参数
      </Button>

      <OmniLabelPromptSettingsModal
        open={promptModalOpen}
        fields={promptFields}
        defaults={promptDefaults}
        value={omniPrompt}
        onCancel={() => setPromptModalOpen(false)}
        onOk={(next) => {
          setOmniPrompt(next)
          form.setFieldValue('omni_label_prompt', next)
          setPromptModalOpen(false)
          message.info('提示词已更新，请点击「保存执行参数」写入配置')
        }}
      />
    </Space>
  )
}
