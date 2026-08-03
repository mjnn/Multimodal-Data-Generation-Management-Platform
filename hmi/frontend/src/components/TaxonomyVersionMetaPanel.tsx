import { Alert, Collapse, Descriptions, Select, Space, Table, Tag, Typography, message } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import type {
  TaxonomyDiffChanged,
  TaxonomyDiffResponse,
  TaxonomyImpactResponse,
  TaxonomyNodeDetail,
  TaxonomyVersion,
} from '../api/types'
import { TaxonomyLineageBar } from './TaxonomyLineageBar'
import { formatTaxonomyImpactWarning, formatTaxonomyVersionLabel } from '../utils/taxonomyDisplay'
import { diffTaxonomyNodes } from '../utils/taxonomyDiff'
import { formatTaxonomyDtype, formatTaxonomyField } from '../utils/uiLabels'

interface TaxonomyVersionMetaPanelProps {
  versionId: string
  versions: TaxonomyVersion[]
  isAdmin: boolean
  /** Live editor nodes (includes unsaved add/delete/edit). */
  currentNodes: TaxonomyNodeDetail[]
  dirty?: boolean
}

export function TaxonomyVersionMetaPanel({
  versionId,
  versions,
  isAdmin,
  currentNodes,
  dirty = false,
}: TaxonomyVersionMetaPanelProps) {
  const [impact, setImpact] = useState<TaxonomyImpactResponse | null>(null)
  const [impactLoading, setImpactLoading] = useState(false)
  const [againstId, setAgainstId] = useState<string | null>(null)
  const [parentVersionId, setParentVersionId] = useState<string | null>(null)
  const [againstNodes, setAgainstNodes] = useState<TaxonomyNodeDetail[] | null>(null)
  const [againstLoading, setAgainstLoading] = useState(false)

  const version = useMemo(() => versions.find((v) => v.id === versionId), [versions, versionId])

  const compareOptions = useMemo(
    () =>
      versions
        .filter((v) => v.id !== versionId && v.status !== 'archived')
        .map((v) => ({
          value: v.id,
          label:
            v.id === parentVersionId
              ? `${formatTaxonomyVersionLabel(v)}（直接父版本）`
              : formatTaxonomyVersionLabel(v),
        })),
    [versions, versionId, parentVersionId],
  )

  useEffect(() => {
    void api
      .getTaxonomyLineage(versionId)
      .then((res) => setParentVersionId(res.parent_version_id))
      .catch(() => setParentVersionId(null))
  }, [versionId])

  useEffect(() => {
    const parentInOptions = parentVersionId
      ? compareOptions.find((o) => o.value === parentVersionId)
      : undefined
    if (parentInOptions) {
      setAgainstId(parentInOptions.value)
      return
    }
    const published = versions.find((v) => v.status === 'published')
    if (published && published.id !== versionId) {
      setAgainstId(published.id)
    } else if (compareOptions[0]) {
      setAgainstId(compareOptions[0].value)
    } else {
      setAgainstId(null)
    }
  }, [versionId, versions, compareOptions, parentVersionId])

  const loadImpact = useCallback(async () => {
    if (!isAdmin) return
    setImpactLoading(true)
    try {
      setImpact(await api.getTaxonomyImpact(versionId))
    } catch {
      message.error('加载发布影响面失败')
      setImpact(null)
    } finally {
      setImpactLoading(false)
    }
  }, [versionId, isAdmin])

  useEffect(() => {
    void loadImpact()
  }, [loadImpact])

  useEffect(() => {
    if (!againstId) {
      setAgainstNodes(null)
      return
    }
    setAgainstLoading(true)
    void api
      .getTaxonomyTree(againstId)
      .then((data) => setAgainstNodes(data.nodes.filter((n) => n.is_active !== false)))
      .catch(() => {
        message.error('加载参照版本标签树失败')
        setAgainstNodes(null)
      })
      .finally(() => setAgainstLoading(false))
  }, [againstId])

  const diff = useMemo((): TaxonomyDiffResponse | null => {
    if (!againstId || !againstNodes) return null
    const againstVersion = versions.find((v) => v.id === againstId)
    return diffTaxonomyNodes(currentNodes, againstNodes, {
      baseVersionId: versionId,
      baseVersionCode: version?.version_code ?? null,
      againstVersionId: againstId,
      againstVersionCode: againstVersion?.version_code ?? null,
    })
  }, [againstId, againstNodes, currentNodes, version, versionId, versions])

  const changedColumns: ColumnsType<TaxonomyDiffChanged> = [
    {
      title: '标签 ID',
      dataIndex: 'label_id',
      render: (v: string) => (
        <Typography.Text code style={{ fontSize: 11 }}>
          {v}
        </Typography.Text>
      ),
    },
    {
      title: '变更字段',
      dataIndex: 'fields',
      render: (fields: string[]) => (
        <Space wrap size={4}>
          {fields.map((f) => (
            <Tag key={f}>{formatTaxonomyField(f)}</Tag>
          ))}
        </Space>
      ),
    },
    {
      title: '前 → 后',
      key: 'delta',
      render: (_, row) => (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {row.fields.includes('name')
              ? `${row.before.name ?? '—'} → ${row.after.name ?? '—'}`
            : row.fields.includes('dtype')
              ? `${formatTaxonomyDtype(String(row.before.dtype))} → ${formatTaxonomyDtype(String(row.after.dtype))}`
              : '—'}
        </Typography.Text>
      ),
    },
  ]

  const diffSummary = diff?.summary

  return (
    <div data-testid="taxonomy-version-meta" style={{ marginBottom: 16 }}>
      <Collapse
        size="small"
        defaultActiveKey={['lineage', 'diff']}
        items={[
          {
            key: 'lineage',
            label: '版本血缘',
            children: <TaxonomyLineageBar versionId={versionId} title="" />,
          },
          ...(isAdmin
            ? [
                {
                  key: 'impact',
                  label: '发布影响面',
                  children: impactLoading ? (
                    <Typography.Text type="secondary">加载中…</Typography.Text>
                  ) : impact ? (
                    <Space direction="vertical" style={{ width: '100%' }} size={8}>
                      <Descriptions size="small" column={2}>
                        <Descriptions.Item label="Clip 绑定">
                          {impact.clip_counts.total}（已校核 {impact.clip_counts.reviewed}）
                        </Descriptions.Item>
                        <Descriptions.Item label="数据集契约锁定">
                          {impact.dataset_filter_lock_count}
                        </Descriptions.Item>
                        <Descriptions.Item label="数据集标签引用">
                          {impact.dataset_label_reference_count}
                        </Descriptions.Item>
                        <Descriptions.Item label="子版本">
                          {impact.child_version_ids.length}
                        </Descriptions.Item>
                      </Descriptions>
                      {impact.warnings.map((w) => (
                        <Alert key={w} type="warning" showIcon message={formatTaxonomyImpactWarning(w)} />
                      ))}
                    </Space>
                  ) : (
                    <Typography.Text type="secondary">暂无数据</Typography.Text>
                  ),
                },
              ]
            : []),
          {
            key: 'diff',
            label: '版本对比',
            children: (
              <div data-testid="taxonomy-diff-panel">
                <Space direction="vertical" style={{ width: '100%' }} size={12}>
                  <Space wrap align="center">
                    <Typography.Text type="secondary">当前版本：</Typography.Text>
                    <Tag>{version ? formatTaxonomyVersionLabel(version) : versionId}</Tag>
                    <Typography.Text type="secondary">参照版本：</Typography.Text>
                    <Select
                      data-testid="taxonomy-diff-against-select"
                      style={{ minWidth: 200 }}
                      placeholder="选择参照版本"
                      options={compareOptions}
                      value={againstId}
                      onChange={setAgainstId}
                      disabled={compareOptions.length === 0}
                    />
                  </Space>
                  <Typography.Paragraph type="secondary" style={{ marginBottom: 0, fontSize: 12 }}>
                    相对参照版本，展示当前版本的节点新增、删除与字段变更；编辑标签树后会即时更新（含未保存修改）。
                    默认与克隆来源（直接父版本）对比；若选已发布版，会包含历史版本间的结构差异。
                  </Typography.Paragraph>
                  {dirty ? (
                    <Tag color="orange" style={{ marginTop: 4 }}>
                      含未保存预览
                    </Tag>
                  ) : null}
                  {compareOptions.length === 0 ? (
                    <Typography.Text type="secondary">无其他版本可对比</Typography.Text>
                  ) : againstLoading ? (
                    <Typography.Text type="secondary">加载版本差异…</Typography.Text>
                  ) : diff ? (
                    <>
                      <Space wrap style={{ marginBottom: 8 }}>
                        <Tag color="green">新增 {diffSummary?.added ?? 0}</Tag>
                        <Tag color="red">删除 {diffSummary?.removed ?? 0}</Tag>
                        <Tag color="blue">变更 {diffSummary?.changed ?? 0}</Tag>
                      </Space>
                      {diff.added_label_ids.length > 0 ? (
                        <>
                          <Typography.Text strong style={{ fontSize: 12 }}>
                            新增节点
                          </Typography.Text>
                          <Space wrap size={4} style={{ display: 'flex', marginBottom: 8 }}>
                            {diff.added_label_ids.map((id) => (
                              <Tag key={id} color="green">
                                {id}
                              </Tag>
                            ))}
                          </Space>
                        </>
                      ) : null}
                      {diff.removed_label_ids.length > 0 ? (
                        <>
                          <Typography.Text strong style={{ fontSize: 12 }}>
                            删除节点
                          </Typography.Text>
                          <Space wrap size={4} style={{ display: 'flex', marginBottom: 8 }}>
                            {diff.removed_label_ids.map((id) => (
                              <Tag key={id} color="red">
                                {id}
                              </Tag>
                            ))}
                          </Space>
                        </>
                      ) : null}
                      {diff.changed.length > 0 ? (
                        <Table
                          size="small"
                          rowKey="label_id"
                          pagination={false}
                          columns={changedColumns}
                          dataSource={diff.changed}
                        />
                      ) : null}
                      {diffSummary &&
                      diffSummary.added === 0 &&
                      diffSummary.removed === 0 &&
                      diffSummary.changed === 0 ? (
                        <Typography.Text type="secondary">两版本节点定义一致</Typography.Text>
                      ) : null}
                    </>
                  ) : null}
                </Space>
              </div>
            ),
          },
        ]}
      />
    </div>
  )
}
