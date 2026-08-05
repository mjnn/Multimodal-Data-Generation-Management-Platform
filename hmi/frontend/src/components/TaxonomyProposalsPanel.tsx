import { Button, Drawer, Form, Input, Modal, Select, Space, Table, Tag, Typography, message } from 'antd'
import type { ColumnsType, TablePaginationConfig } from 'antd/es/table'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { useAuth } from '../auth/AuthContext'
import { canBrowseClips, canManageTaxonomy } from '../auth/roles'
import type { TaxonomyNodeDetail, TaxonomyProposal, TaxonomyVersion } from '../api/types'
import { TaxonomyTreeEditor } from './TaxonomyTreeEditor'
import { formatProposalStatus, formatProposalType } from '../utils/uiLabels'
import { formatTaxonomyVersionLabel } from '../utils/taxonomyDisplay'
import { nodesToPayload, type TaxonomyLevelMeta } from '../utils/taxonomyTree'
import { apiErrorMessage } from '../utils/apiError'

const STATUS_COLOR: Record<string, string> = {
  open: 'processing',
  merged: 'success',
  rejected: 'default',
}

type CreateProposalForm = {
  title: string
  base_version_id: string
  evidence_note: string
  version_code?: string
}

function isReleasedBase(v: TaxonomyVersion): boolean {
  return (
    v.status === 'published' ||
    (v.status === 'archived' && v.archive_reason === 'superseded')
  )
}

export function TaxonomyProposalsPanel({
  onProposalChanged,
}: {
  onProposalChanged?: () => void
} = {}) {
  const { user } = useAuth()
  const canList = canBrowseClips(user?.roles)
  const canCreate = canBrowseClips(user?.roles)
  const canPatch = canManageTaxonomy(user?.roles)

  const [status, setStatus] = useState<string | undefined>('open')
  const [items, setItems] = useState<TaxonomyProposal[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(10)
  const [loading, setLoading] = useState(false)
  const [detail, setDetail] = useState<TaxonomyProposal | null>(null)
  const [createOpen, setCreateOpen] = useState(false)
  const [creating, setCreating] = useState(false)
  const [baseVersions, setBaseVersions] = useState<TaxonomyVersion[]>([])
  const [nodes, setNodes] = useState<TaxonomyNodeDetail[]>([])
  const [emptyLevels, setEmptyLevels] = useState<TaxonomyLevelMeta[]>([])
  const [treeLoading, setTreeLoading] = useState(false)
  const [form] = Form.useForm<CreateProposalForm>()
  const baseVersionId = Form.useWatch('base_version_id', form)

  const load = useCallback(async () => {
    if (!canList) return
    setLoading(true)
    try {
      const res = await api.listTaxonomyProposals({
        status: status || undefined,
        limit: pageSize,
        offset: (page - 1) * pageSize,
      })
      setItems(res.items)
      setTotal(res.total)
    } catch {
      message.error('加载提案失败')
    } finally {
      setLoading(false)
    }
  }, [canList, status, page, pageSize])

  useEffect(() => {
    void load()
  }, [load])

  const onTableChange = (pagination: TablePaginationConfig) => {
    if (pagination.pageSize != null && pagination.pageSize !== pageSize) {
      setPageSize(pagination.pageSize)
      setPage(1)
      return
    }
    if (pagination.current != null && pagination.current !== page) {
      setPage(pagination.current)
    }
  }

  const openCreate = async () => {
    form.resetFields()
    setNodes([])
    setEmptyLevels([])
    setCreateOpen(true)
    try {
      const versions = await api.listTaxonomyVersions()
      const released = versions.filter(isReleasedBase)
      setBaseVersions(released)
      const published = released.find((v) => v.status === 'published')
      const draftEvidence = sessionStorage.getItem('taxonomy_proposal_evidence_draft')
      if (draftEvidence) {
        form.setFieldsValue({ evidence_note: draftEvidence })
        sessionStorage.removeItem('taxonomy_proposal_evidence_draft')
      }
      if (published) {
        form.setFieldsValue({ base_version_id: published.id })
      }
    } catch {
      message.error('加载已发布版本失败')
    }
  }

  useEffect(() => {
    if (!createOpen || !baseVersionId) {
      return
    }
    let cancelled = false
    setTreeLoading(true)
    void api
      .getTaxonomyTree(baseVersionId)
      .then((data) => {
        if (cancelled) return
        setNodes(data.nodes.map((n) => ({ ...n })))
        setEmptyLevels([])
      })
      .catch((e) => {
        if (!cancelled) message.error(apiErrorMessage(e, '加载标签树失败'))
      })
      .finally(() => {
        if (!cancelled) setTreeLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [createOpen, baseVersionId])

  const approveDraft = async (id: string) => {
    try {
      await api.approveTaxonomyProposalDraft(id)
      message.success('已通过审核，提案版本已转为草稿')
      setDetail(null)
      void load()
      onProposalChanged?.()
    } catch {
      message.error('审核失败')
    }
  }

  const rejectProposal = async (id: string) => {
    try {
      await api.patchTaxonomyProposal(id, { status: 'rejected' })
      message.success('已拒绝')
      setDetail(null)
      void load()
      onProposalChanged?.()
    } catch {
      message.error('更新失败')
    }
  }

  const submitCreate = async () => {
    const values = await form.validateFields()
    if (!nodes.some((n) => n.is_active !== false)) {
      message.warning('提案标签树不能为空，请至少保留一个节点')
      return
    }
    setCreating(true)
    try {
      const versionCode =
        typeof values.version_code === 'string' ? values.version_code.trim() : ''
      await api.createTaxonomyProposal({
        title: values.title.trim(),
        base_version_id: values.base_version_id,
        evidence: {
          source: 'manual',
          note: values.evidence_note.trim(),
        },
        nodes: nodesToPayload(nodes),
        ...(versionCode ? { version_code: versionCode } : {}),
      })
      message.success('提案已创建，可在「版本」页查看提案中标签树')
      setCreateOpen(false)
      form.resetFields()
      setNodes([])
      setStatus('open')
      void load()
      onProposalChanged?.()
    } catch (e) {
      message.error(apiErrorMessage(e, '创建提案失败'))
    } finally {
      setCreating(false)
    }
  }

  const baseOptions = useMemo(
    () =>
      baseVersions.map((v) => ({
        value: v.id,
        label: formatTaxonomyVersionLabel(v),
      })),
    [baseVersions],
  )

  if (!canList) {
    return (
      <Typography.Text type="secondary">需要管理员分配的业务角色方可查看提案队列。</Typography.Text>
    )
  }

  const columns: ColumnsType<TaxonomyProposal> = [
    { title: '标题', dataIndex: 'title', ellipsis: true },
    {
      title: '类型',
      dataIndex: 'proposal_type',
      width: 120,
      render: (v: string) => <Tag>{formatProposalType(v)}</Tag>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (v: string) => <Tag color={STATUS_COLOR[v] ?? 'default'}>{formatProposalStatus(v)}</Tag>,
    },
    {
      title: '提案版本',
      key: 'version',
      width: 120,
      render: (_, row) =>
        row.taxonomy_version_id ? (
          <Link to={`/taxonomy/${encodeURIComponent(row.taxonomy_version_id)}?tab=versions`}>查看</Link>
        ) : (
          '—'
        ),
    },
    {
      title: '操作',
      key: 'action',
      width: 100,
      render: (_, row) => {
        const isReviewAction = canPatch && row.status === 'open'
        return (
          <Button type="link" size="small" onClick={() => setDetail(row)}>
            {isReviewAction ? '审核' : '详情'}
          </Button>
        )
      },
    },
  ]

  return (
    <div data-testid="taxonomy-proposals-panel">
      <Typography.Paragraph type="secondary" style={{ marginBottom: 12, fontSize: 12 }}>
        选择<strong>已发布</strong>标签树为 base，在树上增删改后提交整棵树作为提案产物；管理员审核通过后转为草稿。
        {canPatch ? '' : ' 审核与发布需管理员或标签树管理员操作。'}
      </Typography.Paragraph>
      <Space style={{ marginBottom: 12 }} wrap>
        <Select
          allowClear
          placeholder="状态"
          style={{ width: 140 }}
          value={status}
          onChange={(v) => {
            setStatus(v)
            setPage(1)
          }}
          options={[
            { value: 'open', label: '待处理' },
            { value: 'merged', label: '已合并' },
            { value: 'rejected', label: '已拒绝' },
          ]}
        />
        <Button onClick={() => void load()}>刷新</Button>
        {canCreate ? (
          <Button type="primary" onClick={() => void openCreate()}>
            新建提案
          </Button>
        ) : null}
      </Space>
      <Table
        rowKey="id"
        size="small"
        loading={loading}
        columns={columns}
        dataSource={items}
        onChange={onTableChange}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          pageSizeOptions: ['10', '20', '50'],
          showTotal: (n) => `共 ${n} 条`,
        }}
        locale={{
          emptyText: canCreate
            ? '暂无提案。可基于已发布版本编辑标签树并提交修订建议。'
            : '暂无提案。',
        }}
      />

      <Modal
        title="新建标签树完善提案"
        open={createOpen}
        onCancel={() => {
          setCreateOpen(false)
          form.resetFields()
          setNodes([])
        }}
        onOk={() => void submitCreate()}
        confirmLoading={creating}
        okText="提交提案"
        destroyOnClose
        width={920}
        styles={{ body: { maxHeight: 'calc(100vh - 200px)', overflowY: 'auto' } }}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="title" label="标题" rules={[{ required: true, message: '请输入标题' }]}>
            <Input placeholder="例如：补充天气枚举并调整层级命名" />
          </Form.Item>
          <Form.Item
            name="version_code"
            label="版本号"
            extra="选填。不填则系统生成（如 proposal-a1b2c3d4）；填写则使用你指定的版本号（需全局唯一）。"
          >
            <Input placeholder="选填，例如 weather-v2-proposal" allowClear />
          </Form.Item>
          <Form.Item
            name="base_version_id"
            label="Base 已发布版本"
            rules={[{ required: true, message: '请选择 base 版本' }]}
            extra="提案将基于该版本的标签树编辑；提交后生成「提案中」版本。"
          >
            <Select
              showSearch
              optionFilterProp="label"
              placeholder="选择已发布版本"
              options={baseOptions}
              notFoundContent="暂无已发布版本"
            />
          </Form.Item>
          <Form.Item
            name="evidence_note"
            label="证据说明"
            rules={[{ required: true, message: '请填写证据说明' }]}
            extra="请写明为何改树、依据哪些 clip/业务场景、期望效果等。"
          >
            <Input.TextArea rows={4} placeholder="必填：改树依据与证据…" />
          </Form.Item>
        </Form>

        <Typography.Text strong style={{ display: 'block', marginBottom: 8 }}>
          提案标签树（可增删、拖动排序）
        </Typography.Text>
        {treeLoading ? (
          <Typography.Text type="secondary">加载 base 标签树…</Typography.Text>
        ) : baseVersionId ? (
          <TaxonomyTreeEditor
            versionId={baseVersionId}
            nodes={nodes}
            emptyLevels={emptyLevels}
            canEdit
            onNodesChange={setNodes}
            onEmptyLevelsChange={setEmptyLevels}
          />
        ) : (
          <Typography.Text type="secondary">请先选择 base 已发布版本。</Typography.Text>
        )}
      </Modal>

      <Drawer
        title={
          detail
            ? canPatch && detail.status === 'open'
              ? `审核提案 · ${detail.title}`
              : `提案详情 · ${detail.title}`
            : '提案'
        }
        open={Boolean(detail)}
        onClose={() => setDetail(null)}
        width={520}
        extra={
          canPatch && detail?.status === 'open' ? (
            <Space>
              <Button onClick={() => void rejectProposal(detail.id)}>拒绝</Button>
              <Button type="primary" onClick={() => void approveDraft(detail.id)}>
                通过并转为草稿
              </Button>
            </Space>
          ) : null
        }
      >
        {detail ? (
          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            <Typography.Text type="secondary">类型：{formatProposalType(detail.proposal_type)}</Typography.Text>
            {detail.suggested_patch_json && typeof detail.suggested_patch_json === 'object' ? (
              <Typography.Text>
                Base 版本:{' '}
                {(detail.suggested_patch_json as { base_version_id?: string }).base_version_id ? (
                  <Link
                    to={`/taxonomy/${encodeURIComponent(
                      String((detail.suggested_patch_json as { base_version_id?: string }).base_version_id),
                    )}?tab=versions`}
                  >
                    {(detail.suggested_patch_json as { base_version_id?: string }).base_version_id}
                  </Link>
                ) : (
                  '—'
                )}
              </Typography.Text>
            ) : null}
            {detail.taxonomy_version_id ? (
              <Typography.Text>
                提案版本:{' '}
                <Link to={`/taxonomy/${encodeURIComponent(detail.taxonomy_version_id)}?tab=versions`}>
                  在版本页查看
                </Link>
              </Typography.Text>
            ) : null}
            <Typography.Paragraph>
              <Typography.Text type="secondary">证据</Typography.Text>
              <pre style={{ fontSize: 12, whiteSpace: 'pre-wrap' }}>
                {typeof detail.evidence?.note === 'string'
                  ? detail.evidence.note
                  : JSON.stringify(detail.evidence, null, 2)}
              </pre>
            </Typography.Paragraph>
          </Space>
        ) : null}
      </Drawer>
    </div>
  )
}
