import { PlusOutlined, SaveOutlined, ApartmentOutlined } from '@ant-design/icons'

import {

  Button,

  Drawer,

  Form,

  Input,

  Modal,

  Popconfirm,

  Space,

  Switch,

  Table,

  Tag,

  Typography,

  Upload,

  message,

  Tabs,

} from 'antd'

import type { ColumnsType } from 'antd/es/table'

import { useCallback, useEffect, useMemo, useState } from 'react'

import { useNavigate, useParams, useSearchParams } from 'react-router-dom'

import { api } from '../api'

import type { TaxonomyNodeDetail, TaxonomyVersion } from '../api/types'

import { TaxonomyTreeEditor } from '../components/TaxonomyTreeEditor'
import { TaxonomyContextBar } from '../components/TaxonomyContextBar'
import { TaxonomyInsightsPanel } from '../components/TaxonomyInsightsPanel'
import { TaxonomyLineageBar } from '../components/TaxonomyLineageBar'
import { TaxonomyProposalsPanel } from '../components/TaxonomyProposalsPanel'
import { TaxonomyVersionMetaPanel } from '../components/TaxonomyVersionMetaPanel'

import { useAuth } from '../auth/AuthContext'

import { canManageTaxonomy } from '../auth/roles'

import { ContentCard, PageHeader, PageStack } from '../components/ui'

import { nodesToPayload, type TaxonomyLevelMeta } from '../utils/taxonomyTree'
import { formatTaxonomyImpactWarning } from '../utils/taxonomyDisplay'



const STATUS_COLOR: Record<string, string> = {

  draft: 'processing',

  published: 'success',

  archived: 'default',

}



const STATUS_LABEL: Record<string, string> = {

  draft: '草稿',

  published: '已发布',

  archived: '已删除',

}



function isReleasedTaxonomyVersion(row: TaxonomyVersion): boolean {
  return (
    row.status === 'published' ||
    (row.status === 'archived' && row.archive_reason === 'superseded')
  )
}

function versionStatusLabel(row: TaxonomyVersion): string {
  if (isReleasedTaxonomyVersion(row)) {
    return '已发布'
  }
  return STATUS_LABEL[row.status] ?? row.status
}

function versionStatusColor(row: TaxonomyVersion): string {
  if (isReleasedTaxonomyVersion(row)) {
    return STATUS_COLOR.published ?? 'success'
  }
  return STATUS_COLOR[row.status] ?? 'default'
}



function apiErrorMessage(e: unknown, fallback: string): string {

  const detail = (e as { response?: { data?: { detail?: { message?: string } } } })?.response?.data

    ?.detail?.message

  return detail ?? fallback

}



export function TaxonomyPage() {

  const { versionId } = useParams<{ versionId?: string }>()

  const navigate = useNavigate()

  const [searchParams, setSearchParams] = useSearchParams()

  const hubTab = searchParams.get('tab') || 'versions'

  const { user } = useAuth()

  const isAdmin = canManageTaxonomy(user?.roles)



  const [versions, setVersions] = useState<TaxonomyVersion[]>([])

  const [versionsLoading, setVersionsLoading] = useState(false)

  const [treeLoading, setTreeLoading] = useState(false)

  const [nodes, setNodes] = useState<TaxonomyNodeDetail[]>([])

  const [emptyLevels, setEmptyLevels] = useState<TaxonomyLevelMeta[]>([])

  const [selectedVersion, setSelectedVersion] = useState<TaxonomyVersion | null>(null)

  const [dirty, setDirty] = useState(false)

  const [saving, setSaving] = useState(false)



  const [createOpen, setCreateOpen] = useState(false)

  const [createYamlContent, setCreateYamlContent] = useState<string | null>(null)

  const [cloneOpen, setCloneOpen] = useState(false)

  const [cloneSource, setCloneSource] = useState<TaxonomyVersion | null>(null)



  const [createForm] = Form.useForm<{ version_code: string; import_yaml: boolean }>()

  const createImportYaml = Form.useWatch('import_yaml', createForm)

  const [cloneForm] = Form.useForm<{ version_code: string }>()



  const loadVersions = useCallback(async () => {

    setVersionsLoading(true)

    try {

      setVersions(await api.listTaxonomyVersions())

    } catch {

      message.error('加载版本列表失败')

    } finally {

      setVersionsLoading(false)

    }

  }, [])



  const loadTree = useCallback(async (id: string) => {

    setTreeLoading(true)

    try {

      const data = await api.getTaxonomyTree(id)

      if (data.version.status === 'archived' && data.version.archive_reason !== 'superseded') {

        message.warning('该版本已删除')

        navigate('/taxonomy')

        return

      }

      setSelectedVersion(data.version)

      setNodes(data.nodes.filter((n) => n.is_active !== false))

      setEmptyLevels([])

      setDirty(false)

    } catch {

      message.error('加载标签树失败')

      setSelectedVersion(null)

      setNodes([])

      setEmptyLevels([])

    } finally {

      setTreeLoading(false)

    }

  }, [navigate])



  useEffect(() => {

    void loadVersions()

  }, [loadVersions])



  useEffect(() => {

    if (versionId) {

      void loadTree(versionId)

    } else {

      setSelectedVersion(null)

      setNodes([])

      setEmptyLevels([])

      setDirty(false)

    }

  }, [versionId, loadTree])



  const canEdit = isAdmin && selectedVersion?.status === 'draft'



  const handleNodesChange = (next: TaxonomyNodeDetail[]) => {

    setNodes(next)

    setDirty(true)

  }



  const handleEmptyLevelsChange = (next: TaxonomyLevelMeta[]) => {

    setEmptyLevels(next)

    setDirty(true)

  }



  const openVersion = (id: string) => {

    navigate(`/taxonomy/${encodeURIComponent(id)}`)

  }



  const closeVersion = () => {

    navigate('/taxonomy')

  }



  const releasedVersions = useMemo(

    () => versions.filter(isReleasedTaxonomyVersion),

    [versions],

  )



  const draftVersions = useMemo(

    () => (isAdmin ? versions.filter((v) => v.status === 'draft') : []),

    [versions, isAdmin],

  )

  const publishedVersionId = useMemo(
    () => versions.find((v) => v.status === 'published')?.id ?? null,
    [versions],
  )



  const onCreate = async () => {

    const values = await createForm.validateFields()

    if (values.import_yaml && !createYamlContent?.trim()) {

      message.error('请上传本地 YAML 文件')

      return

    }

    try {

      const versionCode = values.version_code.trim()

      const created = values.import_yaml

        ? await api.importTaxonomyYamlVersion({

            version_code: versionCode,

            yaml_content: createYamlContent ?? '',

          })

        : await api.createTaxonomyVersion({

            version_code: versionCode,

            import_yaml: false,

          })

      message.success('版本已创建')

      setCreateOpen(false)

      createForm.resetFields()

      setCreateYamlContent(null)

      await loadVersions()

      openVersion(created.id)

    } catch (e) {

      message.error(apiErrorMessage(e, '创建失败'))

    }

  }



  const onClone = async () => {

    if (!cloneSource) return

    const values = await cloneForm.validateFields()

    try {

      const cloned = await api.cloneTaxonomyVersion(cloneSource.id, {

        version_code: values.version_code.trim(),

      })

      message.success('已克隆为新草稿')

      setCloneOpen(false)

      cloneForm.resetFields()

      setCloneSource(null)

      await loadVersions()

      openVersion(cloned.id)

    } catch (e) {

      message.error(apiErrorMessage(e, '克隆失败'))

    }

  }



  const onPublish = async (row: TaxonomyVersion) => {
    try {
      const impact = await api.getTaxonomyImpact(row.id)
      Modal.confirm({
        title: `确认发布 · ${row.version_code}`,
        width: 480,
        content: (
          <Space direction="vertical" size={8} style={{ width: '100%' }}>
            <Typography.Text>
              Clip 绑定 {impact.clip_counts.total} 条（已校核 {impact.clip_counts.reviewed}）
            </Typography.Text>
            <Typography.Text type="secondary">
              数据集契约锁定 {impact.dataset_filter_lock_count} · 标签引用{' '}
              {impact.dataset_label_reference_count}
            </Typography.Text>
            {impact.warnings.map((w) => (
              <Typography.Text key={w} type="warning">
                {formatTaxonomyImpactWarning(w)}
              </Typography.Text>
            ))}
          </Space>
        ),
        okText: '确认发布',
        cancelText: '取消',
        onOk: async () => {
          await api.publishTaxonomyVersion(row.id)
          message.success('已发布')
          await loadVersions()
          if (versionId === row.id) await loadTree(row.id)
        },
      })
    } catch (e) {
      message.error(apiErrorMessage(e, '发布失败'))
    }
  }



  const onArchive = async (row: TaxonomyVersion) => {

    try {

      await api.archiveTaxonomyVersion(row.id)

      message.success('已删除')

      await loadVersions()

      if (versionId === row.id) navigate('/taxonomy')

    } catch (e) {

      message.error(apiErrorMessage(e, '删除失败'))

    }

  }



  const onSaveAll = async () => {

    if (!selectedVersion || !canEdit) return

    if (nodes.length === 0) {

      message.error('至少保留一个标签节点后再保存（空层级需先添加标签）')

      return

    }

    setSaving(true)

    try {

      await api.replaceTaxonomyNodes(selectedVersion.id, nodesToPayload(nodes))

      message.success('标签树已保存')

      setDirty(false)

      setEmptyLevels([])

      await loadVersions()

      await loadTree(selectedVersion.id)

    } catch (e) {

      message.error(apiErrorMessage(e, '保存失败'))

    } finally {

      setSaving(false)

    }

  }



  const versionColumns: ColumnsType<TaxonomyVersion> = [

    { title: '版本号', dataIndex: 'version_code', key: 'version_code' },

    {

      title: '状态',

      dataIndex: 'status',

      key: 'status',

      render: (_status: string, row) => (

        <Tag color={versionStatusColor(row)}>{versionStatusLabel(row)}</Tag>

      ),

    },

    { title: '节点数', dataIndex: 'node_count', key: 'node_count', width: 80 },

    {

      title: '发布时间',

      dataIndex: 'published_at',

      key: 'published_at',

      render: (v: string | null) => (v ? api.formatDateTime(v) : '—'),

    },

    {

      title: '操作',

      key: 'actions',

      render: (_, row) => (

        <Space size="small" wrap>

          <Button type="link" size="small" onClick={() => openVersion(row.id)}>

            查看

          </Button>

          {isAdmin && row.status === 'draft' ? (

            <Button type="link" size="small" onClick={() => void onPublish(row)}>

              发布

            </Button>

          ) : null}

          {isAdmin ? (

            <Button

              type="link"

              size="small"

              onClick={() => {

                setCloneSource(row)

                cloneForm.setFieldsValue({ version_code: `${row.version_code}-draft` })

                setCloneOpen(true)

              }}

            >

              克隆

            </Button>

          ) : null}

          {isAdmin && row.status !== 'archived' ? (

            <Popconfirm title="确认删除此版本？" onConfirm={() => void onArchive(row)}>

              <Button type="link" size="small" danger>

                删除

              </Button>

            </Popconfirm>

          ) : null}

        </Space>

      ),

    },

  ]



  return (

    <PageStack data-testid="taxonomy-page">

      <PageHeader

        title="标签树管理"

        description="浏览已发布标签树；管理员可新建草稿、在查看页编辑后发布。"

        icon={<ApartmentOutlined />}

        extra={

          isAdmin ? (

            <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>

              新建版本

            </Button>

          ) : undefined

        }

      />

      <TaxonomyContextBar />

      <Tabs
        activeKey={hubTab}
        onChange={(key) => setSearchParams(key === 'versions' ? {} : { tab: key })}
        items={[
          {
            key: 'versions',
            label: '版本',
            children: (
              <>
      <ContentCard title="版本血缘">
        <TaxonomyLineageBar versionId={publishedVersionId} />
      </ContentCard>

      <ContentCard title="已发布标签树">

        <Table

          rowKey="id"

          size="small"

          loading={versionsLoading}

          columns={versionColumns}

          dataSource={releasedVersions}

          pagination={{ pageSize: 10 }}

        />

      </ContentCard>



      {isAdmin && draftVersions.length > 0 ? (

        <ContentCard title="草稿版本">

          <Typography.Paragraph type="secondary" style={{ marginTop: 0, marginBottom: 12 }}>

            草稿仅在发布前展示；点击「查看」可编辑并保存。

          </Typography.Paragraph>

          <Table

            rowKey="id"

            size="small"

            loading={versionsLoading}

            columns={versionColumns}

            dataSource={draftVersions}

            pagination={{ pageSize: 5 }}

          />

        </ContentCard>

      ) : null}
              </>
            ),
          },
          {
            key: 'insights',
            label: '标签覆盖率',
            children: (
              <ContentCard title="标签覆盖率">
                <TaxonomyInsightsPanel />
              </ContentCard>
            ),
          },
          {
            key: 'proposals',
            label: '提案队列',
            children: (
              <ContentCard title="标签树完善提案">
                <TaxonomyProposalsPanel />
              </ContentCard>
            ),
          },
        ]}
      />

      <Drawer

        title={

          selectedVersion

            ? `${selectedVersion.version_code} · ${versionStatusLabel(selectedVersion)}`

            : '标签树'

        }

        open={Boolean(versionId)}

        onClose={closeVersion}

        width={920}

        styles={{ body: { paddingTop: 12 } }}

        destroyOnClose

        extra={

          canEdit ? (

            <Button

              type="primary"

              size="small"

              icon={<SaveOutlined />}

              disabled={!dirty}

              loading={saving}

              onClick={() => void onSaveAll()}

            >

              保存

            </Button>

          ) : null

        }

      >

        {!versionId ? null : treeLoading ? (

          <Typography.Text type="secondary">加载中…</Typography.Text>

        ) : (

          <>
            <TaxonomyVersionMetaPanel
              versionId={versionId}
              versions={versions}
              isAdmin={Boolean(isAdmin)}
              currentNodes={nodes}
              dirty={dirty}
            />
            <TaxonomyTreeEditor

            versionId={versionId}

            nodes={nodes}

            emptyLevels={emptyLevels}

            canEdit={canEdit}

            onNodesChange={handleNodesChange}

            onEmptyLevelsChange={handleEmptyLevelsChange}

          />
          </>

        )}

      </Drawer>



      <Modal

        title="新建版本"

        open={createOpen}

        onCancel={() => {

          setCreateOpen(false)

          createForm.resetFields()

          setCreateYamlContent(null)

        }}

        onOk={() => void onCreate()}

        destroyOnHidden

      >

        <Form
          form={createForm}
          layout="vertical"
          style={{ marginTop: 16 }}
          initialValues={{ version_code: 'v1', import_yaml: false }}
        >

          <Form.Item

            name="version_code"

            label="版本号"

            rules={[{ required: true, message: '请输入版本号' }]}

          >

            <Input placeholder="v1" />

          </Form.Item>

          <Form.Item name="import_yaml" label="从 YAML 导入" valuePropName="checked">

            <Switch />

          </Form.Item>

          {createImportYaml ? (
            <Form.Item label="上传 YAML 文件" required>
              <Upload
                accept=".yaml,.yml,text/yaml"
                maxCount={1}
                beforeUpload={(file) => {
                  void file.text().then((text) => setCreateYamlContent(text))
                  return false
                }}
                onRemove={() => {
                  setCreateYamlContent(null)
                }}
              >
                <Button>选择本地 YAML 文件</Button>
              </Upload>
            </Form.Item>
          ) : null}

        </Form>

      </Modal>



      <Modal

        title={cloneSource ? `克隆 · ${cloneSource.version_code}` : '克隆版本'}

        open={cloneOpen}

        onCancel={() => {

          setCloneOpen(false)

          setCloneSource(null)

          cloneForm.resetFields()

        }}

        onOk={() => void onClone()}

        destroyOnHidden

      >

        <Form form={cloneForm} layout="vertical" style={{ marginTop: 16 }}>

          <Form.Item

            name="version_code"

            label="新版本号"

            rules={[{ required: true, message: '请输入新版本号' }]}

          >

            <Input />

          </Form.Item>

        </Form>

      </Modal>

    </PageStack>

  )

}


