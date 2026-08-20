import { SaveOutlined, SettingOutlined } from '@ant-design/icons'
import { Alert, Button, Form, Input, InputNumber, Select, Space, Switch, Tabs, Typography, message } from 'antd'
import { useCallback, useEffect, useState } from 'react'
import { api } from '../../api'
import type {
  BBoxDetectorOption,
  BBoxYoloClassOption,
  BBoxYoloClassPreset,
  DataTypeRecipe,
  OmniLabelPromptFieldMeta,
  PipelineRunSettings,
  TaxonomyArchiveReason,
} from '../../api/types'
import { useDataSourceMode } from '../../context/DataSourceModeContext'
import { apiErrorMessage } from '../../utils/apiError'
import { formatTaxonomyVersionLabel } from '../../utils/taxonomyDisplay'
import { BBoxYoloClassesModal } from './BBoxYoloClassesModal'
import { OmniLabelPromptSettingsModal } from './OmniLabelPromptSettingsModal'

export function PipelineRunSettingsCard({ dataTypeId }: { dataTypeId?: string }) {
  const { dataSource } = useDataSourceMode()
  const cloud = dataSource === 'cloud'
  const [form] = Form.useForm<PipelineRunSettings>()
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [recipe, setRecipe] = useState<DataTypeRecipe | null>(null)
  const [omniModels, setOmniModels] = useState<string[]>(['default'])
  const [embeddingModels, setEmbeddingModels] = useState<string[]>(['default'])
  const [bboxDetectors, setBboxDetectors] = useState<BBoxDetectorOption[]>([])
  const [yoloClassCatalog, setYoloClassCatalog] = useState<BBoxYoloClassOption[]>([])
  const [yoloClassPresets, setYoloClassPresets] = useState<BBoxYoloClassPreset[]>([])
  const [yoloAvailable, setYoloAvailable] = useState(true)
  const [yoloClassesModalOpen, setYoloClassesModalOpen] = useState(false)
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
  const [settingsTab, setSettingsTab] = useState<'models' | 'bbox'>('models')

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
      setBboxDetectors(
        (res.options.bbox_detectors ?? []).filter(
          (d) => d.id !== 'noop' && d.id !== 'stub',
        ),
      )
      setYoloClassCatalog(res.options.bbox_yolo_classes ?? [])
      setYoloClassPresets(res.options.bbox_yolo_presets ?? [])
      setYoloAvailable(res.options.bbox_yolo_available !== false)
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

  useEffect(() => {
    if (!dataTypeId) {
      setRecipe(null)
      return
    }
    let cancelled = false
    void api
      .getDataType(dataTypeId)
      .then((r) => {
        if (!cancelled) setRecipe(r)
      })
      .catch(() => {
        if (!cancelled) setRecipe(null)
      })
    return () => {
      cancelled = true
    }
  }, [dataTypeId])

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
  const bboxEnabled = Form.useWatch('bbox_enabled', form)
  const bboxDetector = Form.useWatch('bbox_detector', form)
  const labelEnabled = recipe?.stages?.label?.enabled !== false
  const embedEnabled = recipe?.stages?.embed?.enabled !== false
  const bboxForced = Boolean(recipe?.bbox?.enabled)

  if (cloud) {
    return (
      <Alert
        type="info"
        showIcon
        message="云端执行参数"
        description="在线触发使用服务端 DataWorks 默认模板（dataworks_sdk_pipeline_defaults.yaml）与 .env（DATAWORKS_* / DPE_IMAGE / OSS_RAM_ROLE_ARN / DATAWORKS_EXTRA_PARAMS）。BBox 检测器参数仅用于本地 SDK，云端预留同名字段，本卡片不写云端。"
      />
    )
  }

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      {recipe ? (
        <Alert
          type="info"
          showIcon
          message={`当前开跑数据类型：${recipe.title}`}
          description={
            [
              labelEnabled ? null : '配方关闭打标阶段，本次执行不会调用 Omni。',
              embedEnabled ? null : '配方关闭向量阶段。',
              bboxForced
                ? `配方强制开启 BBox（${recipe.bbox?.detector || 'opencv'}）；下列全局开关仍可保存，执行时以配方为准。`
                : null,
            ]
              .filter(Boolean)
              .join(' ') || '设置项按该配方开放的阶段生效；保存的是全局默认参数。'
          }
        />
      ) : null}
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        本地 SDK 轮询处理 rosbag 时使用；模型下拉「default」表示跟随环境变量。
      </Typography.Text>
      <Form form={form} layout="vertical" disabled={loading}>
        <Tabs
          activeKey={settingsTab}
          onChange={(k) => setSettingsTab(k as 'models' | 'bbox')}
          items={[
            {
              key: 'models',
              label: '模型与抽样',
              children: (
                <>
                  <Form.Item name="omni_model" label="打标模型 (Omni)">
                    <Select
                      disabled={!labelEnabled}
                      options={omniModels.map((m) => ({ value: m, label: m }))}
                    />
                  </Form.Item>
                  <Form.Item label=" " colon={false}>
                    <Button
                      icon={<SettingOutlined />}
                      disabled={loading || omniModel === undefined || !labelEnabled}
                      onClick={() => setPromptModalOpen(true)}
                    >
                      结构化提示词设置
                    </Button>
                    <Typography.Text type="secondary" style={{ marginLeft: 12, fontSize: 12 }}>
                      微调 Omni 打标角色、规则与用户任务句（标签列表仍随标签树版本生成）
                    </Typography.Text>
                  </Form.Item>
                  <Form.Item name="embedding_model" label="向量化模型">
                    <Select
                      disabled={!embedEnabled}
                      options={embeddingModels.map((m) => ({ value: m, label: m }))}
                    />
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
                </>
              ),
            },
            {
              key: 'bbox',
              label: 'BBox 检测',
              children: (
                <>
                  <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 8 }}>
                    开启后本地 SDK 跑 annotate_bbox 写 bboxes.jsonl；预览仅编码 plain MP4，HMI 用 jsonl 只读/可编辑叠加框。
                  </Typography.Text>
                  <Space wrap size={24} style={{ width: '100%' }}>
                    <Form.Item name="bbox_enabled" label="启用 BBox" valuePropName="checked">
                      <Switch
                        onChange={(checked) => {
                          if (checked) {
                            form.setFieldValue('bbox_in_label_prompt', true)
                            form.setFieldValue('bbox_face_attrs', true)
                            const det = form.getFieldValue('bbox_detector')
                            if (!det || det === 'noop' || det === 'stub') {
                              form.setFieldValue('bbox_detector', 'opencv')
                            }
                          }
                        }}
                      />
                    </Form.Item>
                    <Form.Item name="encode_plain" label="编码 plain MP4" valuePropName="checked">
                      <Switch />
                    </Form.Item>
                    <Form.Item
                      name="bbox_in_label_prompt"
                      label="将 BBox 检出类别写入打标提示"
                      valuePropName="checked"
                      tooltip="bbox 阶段产物写入 Omni 提示中的 Detected objects；关闭则打标不读 bboxes.jsonl"
                    >
                      <Switch disabled={!bboxEnabled} />
                    </Form.Item>
                    <Form.Item
                      name="bbox_face_attrs"
                      label="人脸属性：性别/年龄"
                      valuePropName="checked"
                      tooltip="仅 OpenCV 人脸检测器生效。使用 OpenCV DNN + Gil Levi age/gender 模型；首次运行会下载 ~90MB 权重到 SDK bbox/data/。模型缺失时仍检出人脸，仅无性别/年龄。"
                    >
                      <Switch disabled={!bboxEnabled || bboxDetector !== 'opencv'} />
                    </Form.Item>
                  </Space>
                  {bboxEnabled && bboxDetector === 'opencv' ? (
                    <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 8 }}>
                      OpenCV 路径会在每人脸框上估计性别与年龄段（如 face/female/~28y），写入 bboxes.jsonl、预览框文字，并在开启「写入打标提示」时进入 Detected objects。
                    </Typography.Text>
                  ) : null}
                  <Form.Item
                    name="bbox_detector"
                    label="检测器"
                    tooltip="opencv=Haar 人脸；yolo=需本机 ultralytics（oms-multimodal-sdk[bbox]）"
                  >
                    <Select
                      disabled={!bboxEnabled}
                      options={(bboxDetectors.length
                        ? bboxDetectors
                        : [
                            { id: 'opencv', desc: 'OpenCV Haar' },
                            { id: 'yolo', desc: 'YOLO' },
                          ]
                      ).map((d) => ({
                        value: d.id,
                        label: `${d.id} — ${d.desc}`,
                        disabled: d.id === 'yolo' && !yoloAvailable,
                      }))}
                    />
                  </Form.Item>
                  {bboxEnabled && bboxDetector === 'yolo' && !yoloAvailable ? (
                    <Alert
                      type="warning"
                      showIcon
                      message="本机未安装 ultralytics"
                      description='请执行：pip install -r hmi/requirements-dev.txt（含 oms-multimodal-sdk[bbox]），然后重启 HMI 后端。或改用 opencv。'
                      style={{ marginBottom: 12 }}
                    />
                  ) : null}
                  <Form.Item name="bbox_element" label="默认元素名 (BBOX_ELEMENT)">
                    <Input disabled={!bboxEnabled} placeholder="element" style={{ maxWidth: 280 }} />
                  </Form.Item>
                  {bboxDetector === 'yolo' ? (
                    <Space direction="vertical" size={8} style={{ width: '100%' }}>
                      <Space wrap size={16}>
                        <Form.Item name="bbox_yolo_model" label="YOLO 权重" style={{ marginBottom: 0 }}>
                          <Input disabled={!bboxEnabled} style={{ width: 200 }} />
                        </Form.Item>
                        <Form.Item name="bbox_yolo_conf" label="YOLO conf" style={{ marginBottom: 0 }}>
                          <InputNumber
                            disabled={!bboxEnabled}
                            min={0.01}
                            max={1}
                            step={0.05}
                            style={{ width: 120 }}
                          />
                        </Form.Item>
                      </Space>
                      <Form.Item
                        label="识别类别清单 (BBOX_YOLO_CLASSES)"
                        tooltip="留空=检测全部类别；填写 COCO 类名或 id，逗号分隔。也可用右侧按钮勾选清单。"
                        extra={
                          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                            YOLO（COCO）适合舱内遗留物等多类检测，无 face。人脸请改选检测器 OpenCV；类别清单内有「舱内遗留物」预设。
                          </Typography.Text>
                        }
                      >
                        <Space.Compact style={{ width: '100%', maxWidth: 560 }}>
                          <Form.Item name="bbox_yolo_classes" noStyle>
                            <Input
                              disabled={!bboxEnabled}
                              placeholder="空=全部；例如 person,car,cell phone"
                              allowClear
                            />
                          </Form.Item>
                          <Button
                            disabled={!bboxEnabled}
                            icon={<SettingOutlined />}
                            onClick={() => setYoloClassesModalOpen(true)}
                          >
                            类别清单
                          </Button>
                        </Space.Compact>
                      </Form.Item>
                    </Space>
                  ) : null}
                  <Typography.Text
                    type="secondary"
                    style={{ fontSize: 12, display: 'block', marginTop: 12, marginBottom: 8 }}
                  >
                    预览 MP4 分辨率（影响带框清晰度；改后需重跑 encode）
                  </Typography.Text>
                  <Space wrap size={16}>
                    <Form.Item name="clip_video_max_width" label="最大宽度" style={{ marginBottom: 0 }}>
                      <InputNumber min={640} max={3840} step={160} style={{ width: 120 }} />
                    </Form.Item>
                    <Form.Item name="clip_video_max_height" label="最大高度" style={{ marginBottom: 0 }}>
                      <InputNumber min={360} max={2160} step={90} style={{ width: 120 }} />
                    </Form.Item>
                    <Form.Item
                      name="clip_video_crf"
                      label="CRF"
                      tooltip="越小越清晰、体积越大；默认 18"
                      style={{ marginBottom: 0 }}
                    >
                      <InputNumber min={14} max={28} step={1} style={{ width: 100 }} />
                    </Form.Item>
                  </Space>
                </>
              ),
            },
          ]}
        />
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
      <BBoxYoloClassesModal
        open={yoloClassesModalOpen}
        catalog={yoloClassCatalog}
        presets={yoloClassPresets}
        value={String(form.getFieldValue('bbox_yolo_classes') || '')}
        onCancel={() => setYoloClassesModalOpen(false)}
        onOk={(nextCsv) => {
          form.setFieldValue('bbox_yolo_classes', nextCsv)
          setYoloClassesModalOpen(false)
          message.info('类别清单已更新，请点击「保存执行参数」写入配置')
        }}
      />
    </Space>
  )
}
