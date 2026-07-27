import { PlusOutlined, SaveOutlined, ApartmentOutlined } from '@ant-design/icons'

import {

  Button,

  Col,

  Form,

  Input,

  Modal,

  Popconfirm,

  Row,

  Space,

  Switch,

  Table,

  Tag,

  Typography,

  message,

} from 'antd'

import type { ColumnsType } from 'antd/es/table'

import { useCallback, useEffect, useState } from 'react'

import { useNavigate, useParams } from 'react-router-dom'

import { api } from '../api'

import type { TaxonomyNodeDetail, TaxonomyVersion } from '../api/types'

import { TaxonomyTreeEditor } from '../components/TaxonomyTreeEditor'

import { useAuth } from '../auth/AuthContext'

import { canManageTaxonomy } from '../auth/roles'

import { ContentCard, PageHeader, PageStack } from '../components/ui'

import { nodesToPayload, type TaxonomyLevelMeta } from '../utils/taxonomyTree'



const STATUS_COLOR: Record<string, string> = {

  draft: 'processing',

  published: 'success',

  archived: 'default',

}



const STATUS_LABEL: Record<string, string> = {

  draft: '草稿',

  published: '已发布',

  archived: '已归档',

}



function apiErrorMessage(e: unknown, fallback: string): string {

  const detail = (e as { response?: { data?: { detail?: { message?: string } } } })?.response?.data

    ?.detail?.message

  return detail ?? fallback

}



export function TaxonomyPage() {

  const { versionId } = useParams<{ versionId?: string }>()

  const navigate = useNavigate()

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

  const [cloneOpen, setCloneOpen] = useState(false)

  const [cloneSource, setCloneSource] = useState<TaxonomyVersion | null>(null)



  const [createForm] = Form.useForm<{ version_code: string; import_yaml: boolean }>()

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

      setSelectedVersion(data.version)

      setNodes(data.nodes)

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

  }, [])



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



  const onCreate = async () => {

    const values = await createForm.validateFields()

    try {

      const created = await api.createTaxonomyVersion({

        version_code: values.version_code.trim(),

        import_yaml: values.import_yaml,

      })

      message.success('版本已创建')

      setCreateOpen(false)

      createForm.resetFields()

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

      await api.publishTaxonomyVersion(row.id)

      message.success('已发布')

      await loadVersions()

      if (versionId === row.id) await loadTree(row.id)

    } catch (e) {

      message.error(apiErrorMessage(e, '发布失败'))

    }

  }



  const onArchive = async (row: TaxonomyVersion) => {

    try {

      await api.archiveTaxonomyVersion(row.id)

      message.success('已归档')

      await loadVersions()

      if (versionId === row.id) await loadTree(row.id)

    } catch (e) {

      message.error(apiErrorMessage(e, '归档失败'))

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

      render: (status: string) => (

        <Tag color={STATUS_COLOR[status] ?? 'default'}>{STATUS_LABEL[status] ?? status}</Tag>

      ),

    },

    { title: '节点数', dataIndex: 'node_count', key: 'node_count', width: 80 },

    {

      title: '发布时间',

      dataIndex: 'published_at',

      key: 'published_at',

      render: (v: string | null) => v ?? '—',

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

            <Popconfirm title="确认发布此版本？" onConfirm={() => void onPublish(row)}>

              <Button type="link" size="small">

                发布

              </Button>

            </Popconfirm>

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

            <Popconfirm title="确认归档？" onConfirm={() => void onArchive(row)}>

              <Button type="link" size="small" danger>

                归档

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

        description="草稿版本支持层级枝干增删改与标签节点维护，发布后供打标与校核引用。"

        icon={<ApartmentOutlined />}

        extra={

          isAdmin ? (

            <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>

              新建版本

            </Button>

          ) : undefined

        }

      />



      <Row gutter={16}>

        <Col xs={24} lg={14}>

          <ContentCard title="版本列表">

            <Table

              rowKey="id"

              size="small"

              loading={versionsLoading}

              columns={versionColumns}

              dataSource={versions}

              pagination={{ pageSize: 8 }}

              rowClassName={(row) => (row.id === versionId ? 'ant-table-row-selected' : '')}

              onRow={(row) => ({

                onClick: () => openVersion(row.id),

                style: { cursor: 'pointer' },

              })}

            />

          </ContentCard>

        </Col>



        <Col xs={24} lg={10}>

          <ContentCard

            title={

              selectedVersion

                ? `${selectedVersion.version_code} · ${STATUS_LABEL[selectedVersion.status] ?? selectedVersion.status}`

                : '标签树'

            }

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

            {!versionId ? (

              <Typography.Text type="secondary">请从左侧选择版本查看标签树</Typography.Text>

            ) : treeLoading ? (

              <Typography.Text type="secondary">加载中…</Typography.Text>

            ) : (

              <TaxonomyTreeEditor

                versionId={versionId}

                nodes={nodes}

                emptyLevels={emptyLevels}

                canEdit={canEdit}

                onNodesChange={handleNodesChange}

                onEmptyLevelsChange={handleEmptyLevelsChange}

              />

            )}

          </ContentCard>

        </Col>

      </Row>



      <Modal

        title="新建版本"

        open={createOpen}

        onCancel={() => {

          setCreateOpen(false)

          createForm.resetFields()

        }}

        onOk={() => void onCreate()}

        destroyOnHidden

      >

        <Form form={createForm} layout="vertical" style={{ marginTop: 16 }}>

          <Form.Item

            name="version_code"

            label="版本号"

            rules={[{ required: true, message: '请输入版本号' }]}

          >

            <Input placeholder="v3" />

          </Form.Item>

          <Form.Item name="import_yaml" label="从 YAML 导入" valuePropName="checked">

            <Switch />

          </Form.Item>

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


