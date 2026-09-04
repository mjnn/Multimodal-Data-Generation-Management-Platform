/**
 * 新建 / 编辑 DataType 配方（admin）。
 * 新建：基本信息模态 → 管线编排页 → 展示页排版；编辑：同页。
 * 保存走 PUT /api/platform/data-types/{id}；校验在后端 recipe.py。
 */
import { SaveOutlined } from '@ant-design/icons'
import {
  Alert,
  AutoComplete,
  Button,
  Card,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Typography,
  message,
} from 'antd'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import type {
  DataTypeRecipe,
  PipelineBinding,
  PipelinePortBindings,
  PipelineStep,
  PlatformCatalog,
  RecipeGraph,
  RecipeOverview,
} from '../api/types'
import { DagNodeInspector } from '../components/datatype/DagNodeInspector'
import '../components/datatype/DagNodeInspector.css'
import { OverviewComposer, OverviewPreview } from '../components/datatype/OverviewComposer'
import '../components/datatype/OverviewPreview.css'
import { PipelineDagCanvas } from '../components/datatype/PipelineDagCanvas'
import { ContentCard, PageHeader, PageStack } from '../components/ui'
import { apiErrorMessage } from '../utils/apiError'
import { cardsFromPreset, hydrateOverview, remapOverviewKeys } from '../utils/overviewLayout'
import { compileSteps, duplicateSourceTitleError, hydrateRecipeToSteps } from '../utils/recipePipeline'
import {
  attachStepBindings,
  defaultNewGraph,
  graphIsLossy,
  graphToSteps,
  hydrateGraphFromSteps,
  remapGraphKeys,
} from '../utils/recipeGraph'

type EditorForm = {
  id: string
  title: string
  purpose: string
  owner: string
  taxonomy_id: string
  overview_view: string
  status: 'draft' | 'published'
}

function emptyMeta(): EditorForm {
  return {
    id: '',
    title: '',
    purpose: '',
    owner: 'platform',
    taxonomy_id: 'oms',
    overview_view: 'cabin_timeline',
    status: 'draft',
  }
}

function recipeToMeta(r: DataTypeRecipe): EditorForm {
  return {
    id: r.id,
    title: r.title,
    purpose: r.purpose,
    owner: r.owner || 'platform',
    taxonomy_id: r.taxonomy_id,
    overview_view: r.overview_view,
    status: r.status === 'published' ? 'published' : 'draft',
  }
}

function remapStepKeys(steps: PipelineStep[], suffix = '-copy'): PipelineStep[] {
  const keymap = new Map(steps.map((s) => [s.key, `${s.key}${suffix}`]))
  const remapBinding = (b: PipelineBinding): PipelineBinding => {
    if (b.kind === 'slot' && keymap.has(b.slot_id)) {
      return { ...b, slot_id: keymap.get(b.slot_id)! }
    }
    if (b.kind === 'upstream' && keymap.has(b.step_key)) {
      return { ...b, step_key: keymap.get(b.step_key)! }
    }
    return b
  }
  const remapPort = (raw: PipelinePortBindings): PipelinePortBindings =>
    Array.isArray(raw) ? raw.map(remapBinding) : remapBinding(raw)
  return steps.map((s) => ({
    ...s,
    key: keymap.get(s.key) ?? s.key,
    bindings: s.bindings
      ? Object.fromEntries(Object.entries(s.bindings).map(([pid, b]) => [pid, remapPort(b)]))
      : s.bindings,
  }))
}

function clonePipelineAndOverview(
  src: DataTypeRecipe,
  catalog: PlatformCatalog | null,
): { steps: PipelineStep[]; overview: RecipeOverview } {
  const ops = catalog?.operators || []
  const steps = hydrateRecipeToSteps(src, ops, catalog?.type_provides || {})
  const keymap = new Map(steps.map((s) => [s.key, `${s.key}-copy`]))
  for (const n of src.graph?.nodes || []) {
    keymap.set(n.key, `${n.key}-copy`)
  }
  return {
    steps: remapStepKeys(steps),
    overview: remapOverviewKeys(hydrateOverview(src, catalog?.views), keymap),
  }
}

function DataTypeMetaFields({
  isNew,
  taxonomyOptions,
  templates,
  catalog,
  onCloneTemplate,
}: {
  isNew: boolean
  taxonomyOptions: { value: string }[]
  templates: DataTypeRecipe[]
  catalog: PlatformCatalog | null
  onCloneTemplate: (id: string) => void
}) {
  return (
    <>
      <Space wrap size={16} style={{ width: '100%' }}>
        <Form.Item
          name="id"
          label="稳定 id"
          rules={[{ required: true, message: '必填' }]}
          style={{ minWidth: 220 }}
        >
          <Input disabled={!isNew} placeholder="例如 cabin_v2" data-testid="dtype-id" />
        </Form.Item>
        <Form.Item
          name="title"
          label="展示名"
          rules={[{ required: true, message: '必填' }]}
          style={{ minWidth: 240 }}
        >
          <Input data-testid="dtype-title" />
        </Form.Item>
        <Form.Item name="owner" label="负责人" style={{ minWidth: 160 }}>
          <Input />
        </Form.Item>
        <Form.Item name="status" label="状态" style={{ minWidth: 140 }}>
          <Select
            options={[
              { value: 'draft', label: 'draft（草稿）' },
              { value: 'published', label: 'published（可开跑）' },
            ]}
          />
        </Form.Item>
      </Space>
      <Form.Item name="purpose" label="用途说明" rules={[{ required: true, message: '必填' }]}>
        <Input.TextArea rows={2} data-testid="dtype-purpose" />
      </Form.Item>
      <Space wrap size={16} style={{ width: '100%' }}>
        <Form.Item
          name="taxonomy_id"
          label="绑定标签树 taxonomy_id"
          rules={[{ required: true, message: '必填' }]}
          style={{ minWidth: 260 }}
          tooltip="一类型一棵树（D4）；填业务树 id，如 oms / audio_nvh"
        >
          <AutoComplete options={taxonomyOptions} placeholder="oms" />
        </Form.Item>
        <Form.Item
          name="overview_view"
          label="从预设填入"
          rules={[{ required: true }]}
          style={{ minWidth: 280 }}
          tooltip="会重置展示页（Clip 详情）组件卡，之后仍可改"
        >
          <Select
            data-testid="dtype-overview-preset"
            options={(catalog?.views || []).map((v) => ({
              value: v.id,
              label: `${v.title}（${v.id}）`,
            }))}
          />
        </Form.Item>
        {isNew ? (
          <Form.Item label="从已有类型复制">
            <Select
              allowClear
              placeholder="可选模板"
              style={{ minWidth: 240 }}
              options={templates.map((t) => ({ value: t.id, label: `${t.title}（${t.id}）` }))}
              onChange={(id: string) => {
                if (id) onCloneTemplate(id)
              }}
            />
          </Form.Item>
        ) : null}
      </Space>
    </>
  )
}

function buildRecipe(
  values: EditorForm,
  graph: RecipeGraph,
  overview: RecipeOverview,
  catalog: PlatformCatalog | null,
): DataTypeRecipe {
  const steps = graphToSteps(graph)
  const compiled = compileSteps(steps, [], catalog?.operators || [])
  return {
    id: String(values.id || '').trim(),
    title: String(values.title || '').trim(),
    purpose: String(values.purpose || '').trim(),
    owner: String(values.owner || 'platform').trim() || 'platform',
    taxonomy_id: String(values.taxonomy_id || '').trim(),
    overview_view: values.overview_view,
    overview: { ...overview, preset: values.overview_view },
    graph,
    status: values.status === 'published' ? 'published' : 'draft',
    require_any_kinds: compiled.require_any_kinds,
    slots: compiled.slots,
    preprocess: compiled.preprocess,
    products: compiled.products,
    stages: compiled.stages,
    bbox: compiled.bbox,
  }
}

export function DataTypeEditorPage() {
  const navigate = useNavigate()
  const { dataTypeId } = useParams<{ dataTypeId: string }>()
  const [searchParams] = useSearchParams()
  const isNew = !dataTypeId || dataTypeId === 'new'
  const [form] = Form.useForm<EditorForm>()
  const [catalog, setCatalog] = useState<PlatformCatalog | null>(null)
  const [templates, setTemplates] = useState<DataTypeRecipe[]>([])
  const [graph, setGraph] = useState<RecipeGraph>(() => defaultNewGraph())
  const [overview, setOverview] = useState<RecipeOverview>(() => cardsFromPreset('cabin_timeline'))
  const [selectedKey, setSelectedKey] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [metaReady, setMetaReady] = useState(() => !isNew)
  const [metaModalOpen, setMetaModalOpen] = useState(() => isNew)
  const [newStage, setNewStage] = useState<'pipeline' | 'overview'>('pipeline')
  const watchedId = Form.useWatch('id', form)
  const watchedTitle = Form.useWatch('title', form)
  const steps = useMemo(() => graphToSteps(graph), [graph])
  const lossy = useMemo(() => graphIsLossy(graph), [graph])
  const showWorkspace = !isNew || metaReady
  const showPipeline = showWorkspace && (!isNew || newStage === 'pipeline')
  const showOverviewPage = Boolean(isNew && showWorkspace && newStage === 'overview')

  const taxonomyOptions = useMemo(() => {
    const ids = new Set<string>(['oms', 'ivi_ui_stub', 'audio_nvh'])
    for (const t of templates) {
      if (t.taxonomy_id) ids.add(t.taxonomy_id)
    }
    return [...ids].map((v) => ({ value: v }))
  }, [templates])

  const load = useCallback(async () => {
    const [cat, list] = await Promise.all([api.listPlatformCatalog(), api.listDataTypes()])
    setCatalog(cat)
    setTemplates(list.items ?? [])
    const ops = cat.operators || []
    if (isNew) {
      const cloneId = searchParams.get('from') || ''
      if (cloneId) {
        const src = list.items?.find((x) => x.id === cloneId) || (await api.getDataType(cloneId))
        const meta = recipeToMeta(src)
        meta.id = ''
        meta.title = `${src.title}（副本）`
        meta.status = 'draft'
        form.setFieldsValue(meta)
        const cloned = clonePipelineAndOverview(src, cat)
        setSelectedKey(null)
        setNewStage('pipeline')
        setGraph(src.graph?.nodes?.length ? remapGraphKeys(src.graph) : hydrateGraphFromSteps(cloned.steps))
        setOverview(cloned.overview)
        return
      }
      form.setFieldsValue(emptyMeta())
      setSelectedKey(null)
      setNewStage('pipeline')
      setGraph(defaultNewGraph())
      setOverview(cardsFromPreset('cabin_timeline', cat.views))
      return
    }
    const rec = await api.getDataType(dataTypeId!)
    form.setFieldsValue(recipeToMeta(rec))
    const loadedSteps = hydrateRecipeToSteps(rec, ops, cat.type_provides || {})
    setSelectedKey(null)
    setGraph(
      attachStepBindings(
        rec.graph?.nodes?.length ? rec.graph : hydrateGraphFromSteps(loadedSteps),
        loadedSteps,
      ),
    )
    setOverview(hydrateOverview(rec, cat.views))
  }, [dataTypeId, form, isNew, searchParams])

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    void load()
      .catch((e: unknown) => {
        if (!cancelled) message.error(apiErrorMessage(e, '加载配方失败'))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [load])

  const cloneTemplate = useCallback(
    (id: string) => {
      void (async () => {
        try {
          const src = await api.getDataType(id)
          const meta = recipeToMeta(src)
          meta.id = ''
          meta.title = `${src.title}（副本）`
          meta.status = 'draft'
          form.setFieldsValue(meta)
          const cloned = clonePipelineAndOverview(src, catalog)
          setSelectedKey(null)
          setNewStage('pipeline')
          setGraph(
            src.graph?.nodes?.length ? remapGraphKeys(src.graph) : hydrateGraphFromSteps(cloned.steps),
          )
          setOverview(cloned.overview)
        } catch (e: unknown) {
          message.error(apiErrorMessage(e, '复制模板失败'))
        }
      })()
    },
    [catalog, form],
  )

  const confirmMeta = async () => {
    const values = await form.validateFields(['id', 'title', 'purpose', 'taxonomy_id', 'overview_view'])
    const id = String(values.id || '').trim()
    if (!/^[a-z][a-z0-9_]*$/.test(id)) {
      message.error('id 须以小写字母开头，仅含小写字母、数字、下划线')
      return
    }
    setMetaReady(true)
    setMetaModalOpen(false)
  }

  const save = async () => {
    const values = await form.validateFields()
    const dup = duplicateSourceTitleError(steps)
    if (dup) {
      message.error(dup)
      return
    }
    let recipe: DataTypeRecipe
    try {
      recipe = buildRecipe(values, graph, overview, catalog)
    } catch (e: unknown) {
      message.error(apiErrorMessage(e, '配方校验失败'))
      return
    }
    if (!recipe.id) {
      message.error('请填写稳定 id（小写字母/数字/下划线）')
      return
    }
    if (!/^[a-z][a-z0-9_]*$/.test(recipe.id)) {
      message.error('id 须以小写字母开头，仅含小写字母、数字、下划线')
      return
    }
    if (!(recipe.slots && recipe.slots.length)) {
      message.error('至少添加一个数据源')
      return
    }
    setSaving(true)
    try {
      const saved = await api.putDataType(recipe.id, recipe)
      message.success(saved.status === 'published' ? '已保存并发布' : '已保存为草稿')
      void navigate('/')
    } catch (e: unknown) {
      message.error(apiErrorMessage(e, '保存失败'))
    } finally {
      setSaving(false)
    }
  }

  const metaFields = (
    <DataTypeMetaFields
      isNew={isNew}
      taxonomyOptions={taxonomyOptions}
      templates={templates}
      catalog={catalog}
      onCloneTemplate={cloneTemplate}
    />
  )

  return (
    <PageStack data-testid="data-type-editor">
      <PageHeader
        title={
          isNew
            ? newStage === 'overview'
              ? '展示页排版'
              : '新建数据类型'
            : `编辑数据类型 · ${dataTypeId}`
        }
        extra={
          <Space>
            {showOverviewPage ? (
              <Button data-testid="dtype-overview-back" onClick={() => setNewStage('pipeline')}>
                返回管线编排
              </Button>
            ) : (
              <Button onClick={() => void navigate('/')}>返回列表</Button>
            )}
            {showPipeline && isNew ? (
              <Button type="primary" data-testid="dtype-overview-open" onClick={() => setNewStage('overview')}>
                进入展示页排版
              </Button>
            ) : showWorkspace ? (
              <Button
                type="primary"
                icon={<SaveOutlined />}
                loading={saving}
                onClick={() => void save()}
                data-testid="dtype-save"
              >
                保存配方
              </Button>
            ) : null}
          </Space>
        }
      />
      <ContentCard>
        {showOverviewPage ? (
          <Typography.Paragraph type="secondary" style={{ marginBottom: 16 }}>
            Clip 详情页按此顺序叠卡。点选预设会重置展示页组件；绑定可选，运行时仍走现有 clip/run 接口。
          </Typography.Paragraph>
        ) : showPipeline ? (
          <>
            <Typography.Paragraph type="secondary" style={{ marginBottom: 16 }}>
              从左侧点选管线组件或控制流节点放到画布上，拖线连接。点选「数据源」增加一路输入。打标器不可删除。
              只能引用已注册算子与展示页组件；默认建议先存 <Typography.Text code>draft</Typography.Text>
              ，验证后再发布。
            </Typography.Paragraph>
            <Alert
              type="info"
              showIcon
              style={{ marginBottom: 16 }}
              message="算子与视图由代码注册"
              description="新算子需发版接入；本表单只组合已有能力。勿对 audio_nvh-v2 标签树做全局 publish（与本配方 status 无关）。"
            />
          </>
        ) : (
          <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
            先填写基本信息，确认后再进入管线编排。
          </Typography.Paragraph>
        )}
        <Form
          form={form}
          layout="vertical"
          disabled={loading}
          onValuesChange={(changed: Partial<EditorForm>) => {
            if (changed.overview_view) {
              setOverview(cardsFromPreset(changed.overview_view, catalog?.views))
            }
          }}
        >
          {isNew ? (
            <Modal
              title="基本信息"
              open={metaModalOpen}
              maskClosable={false}
              destroyOnClose={false}
              onCancel={() => {
                if (metaReady) {
                  setMetaModalOpen(false)
                  return
                }
                void navigate('/')
              }}
              footer={
                <Space>
                  <Button
                    data-testid="dtype-meta-cancel"
                    onClick={() => {
                      if (metaReady) {
                        setMetaModalOpen(false)
                        return
                      }
                      void navigate('/')
                    }}
                  >
                    {metaReady ? '取消' : '返回列表'}
                  </Button>
                  <Button type="primary" data-testid="dtype-meta-confirm" onClick={() => void confirmMeta()}>
                    进入管线编排
                  </Button>
                </Space>
              }
            >
              <div data-testid="dtype-meta-modal">{metaFields}</div>
            </Modal>
          ) : (
            <Card size="small" title="基本信息" style={{ marginBottom: 16 }}>
              {metaFields}
            </Card>
          )}

          {isNew && showPipeline ? (
            <Card size="small" style={{ marginBottom: 16 }} data-testid="dtype-meta-summary">
              <Space wrap align="center" style={{ width: '100%', justifyContent: 'space-between' }}>
                <Typography.Text>
                  <Typography.Text type="secondary">基本信息 · </Typography.Text>
                  <Typography.Text className="mono">{watchedId || '（未填 id）'}</Typography.Text>
                  {watchedTitle ? (
                    <Typography.Text type="secondary"> · {watchedTitle}</Typography.Text>
                  ) : null}
                </Typography.Text>
                <Button size="small" data-testid="dtype-meta-edit" onClick={() => setMetaModalOpen(true)}>
                  修改基本信息
                </Button>
              </Space>
            </Card>
          ) : null}

          {!isNew && showWorkspace ? (
            <Card size="small" title="展示页排版" style={{ marginBottom: 16 }}>
              <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
                Clip 详情页按此顺序叠卡。点选预设会重置展示页组件；绑定可选，运行时仍走现有 clip/run 接口。
              </Typography.Paragraph>
              <OverviewComposer
                overview={overview}
                onChange={setOverview}
                widgets={catalog?.view_widgets || []}
                steps={steps}
                operators={catalog?.operators || []}
                typeProvides={catalog?.type_provides || {}}
              />
            </Card>
          ) : null}

          {showPipeline ? (
            <Card size="small" title={isNew ? undefined : '管线编排'} style={{ marginBottom: 16 }}>
              {isNew ? null : (
                <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
                  从左侧点选管线组件或控制流节点放到画布上，拖线连接。点选「数据源」增加一路输入。打标器不可删除。
                </Typography.Paragraph>
              )}
              <Alert
                type="info"
                showIcon
                style={{ marginBottom: 12 }}
                data-testid="dag-cloud-hint"
                message="本地按图执行；上云只跑公共前缀。"
              />
              {lossy ? (
                <Alert
                  type="warning"
                  showIcon
                  style={{ marginBottom: 12 }}
                  data-testid="dag-cloud-lossy"
                  message="图含 if 或打标后节点：上云不会执行这些分支。"
                />
              ) : null}
              <PipelineDagCanvas
                operators={catalog?.operators || []}
                categoryTitles={catalog?.categories}
                graph={graph}
                onChange={setGraph}
                selectedKey={selectedKey}
                onSelect={setSelectedKey}
              >
                <DagNodeInspector
                  graph={graph}
                  selectedKey={selectedKey}
                  onChange={setGraph}
                  operators={catalog?.operators || []}
                  typeProvides={catalog?.type_provides || {}}
                  sourceKinds={catalog?.source_kinds}
                  disabled={loading}
                  onClose={() => setSelectedKey(null)}
                />
              </PipelineDagCanvas>
            </Card>
          ) : null}

          {showOverviewPage ? (
            <div data-testid="dtype-overview-page">
              <div className="overview-page-split">
                <OverviewComposer
                  overview={overview}
                  onChange={setOverview}
                  widgets={catalog?.view_widgets || []}
                  steps={steps}
                  operators={catalog?.operators || []}
                  typeProvides={catalog?.type_provides || {}}
                />
                <OverviewPreview overview={overview} widgets={catalog?.view_widgets || []} />
              </div>
            </div>
          ) : null}
        </Form>
      </ContentCard>
    </PageStack>
  )
}
