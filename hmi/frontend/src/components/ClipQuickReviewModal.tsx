import { CheckOutlined, SaveOutlined } from '@ant-design/icons'
import type { AxiosError } from 'axios'
import { Button, Form, Modal, Space, Spin, message } from 'antd'
import { useCallback, useEffect, useState } from 'react'
import { api } from '../api'
import type { ClipLabelReview, ReviewStatus, TaxonomyNodeDetail } from '../api/types'
import { ReviewTaxonomyForm } from './ReviewTaxonomyForm'
import { apiErrorMessage } from '../utils/apiError'

type ClipQuickReviewModalProps = {
  open: boolean
  clipId: string
  runId: string
  onClose: () => void
  onSaved?: (review: ClipLabelReview) => void
}

export function ClipQuickReviewModal({
  open,
  clipId,
  runId,
  onClose,
  onSaved,
}: ClipQuickReviewModalProps) {
  const [form] = Form.useForm<Record<string, unknown>>()
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [review, setReview] = useState<ClipLabelReview | null>(null)
  const [taxonomyNodes, setTaxonomyNodes] = useState<TaxonomyNodeDetail[]>([])

  const loadTaxonomy = useCallback(async (versionId: string | null) => {
    if (versionId) {
      const tree = await api.getTaxonomyTree(versionId)
      setTaxonomyNodes(tree.nodes)
      return
    }
    const versions = await api.listTaxonomyVersions()
    const published = versions.find((v) => v.status === 'published')
    if (published) {
      const tree = await api.getTaxonomyTree(published.id)
      setTaxonomyNodes(tree.nodes)
    } else {
      setTaxonomyNodes([])
    }
  }, [])

  const loadReview = useCallback(async () => {
    if (!clipId || !runId) return
    setLoading(true)
    try {
      let detail: ClipLabelReview
      try {
        detail = await api.getReviewDetail(clipId, runId)
      } catch (e) {
        const status = (e as AxiosError)?.response?.status
        if (status === 404) {
          detail = await api.ensureReview(clipId, runId)
        } else {
          throw e
        }
      }
      setReview(detail)
      form.setFieldsValue(detail.labels_json ?? {})
      await loadTaxonomy(detail.taxonomy_version_id)
    } catch (e) {
      message.error(apiErrorMessage(e, '加载校核数据失败'))
      onClose()
    } finally {
      setLoading(false)
    }
  }, [clipId, form, loadTaxonomy, onClose, runId])

  useEffect(() => {
    if (open) {
      void loadReview()
    } else {
      setReview(null)
      form.resetFields()
    }
  }, [open, loadReview, form])

  const persist = async (reviewStatus: ReviewStatus) => {
    if (!review) return false
    setSaving(true)
    try {
      const edited = form.getFieldsValue(true) as Record<string, unknown>
      const updated = await api.saveReview(review.clip_id, {
        labels_json: edited,
        review_status: reviewStatus,
        updated_at: review.updated_at,
        run_id: review.run_id,
      })
      setReview(updated)
      form.setFieldsValue(updated.labels_json ?? {})
      message.success(reviewStatus === 'reviewed' ? '已确认校核' : '草稿已保存')
      onSaved?.(updated)
      if (reviewStatus === 'reviewed') {
        onClose()
      }
      return true
    } catch (e) {
      const status = (e as AxiosError)?.response?.status
      if (status === 409) {
        Modal.warning({
          title: '版本冲突',
          content: '记录已被他人修改，请关闭后重试。',
          onOk: () => void loadReview(),
        })
      } else {
        message.error(apiErrorMessage(e, '保存失败'))
      }
      return false
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      title="快速校核"
      open={open}
      onCancel={onClose}
      width={720}
      destroyOnClose
      footer={
        loading || !review ? null : (
          <Space>
            <Button onClick={onClose}>取消</Button>
            <Button icon={<SaveOutlined />} loading={saving} onClick={() => void persist('pending_review')}>
              保存草稿
            </Button>
            <Button
              type="primary"
              icon={<CheckOutlined />}
              loading={saving}
              onClick={() => void persist('reviewed')}
            >
              完成校核
            </Button>
          </Space>
        )
      }
    >
      {loading || !review ? (
        <div style={{ textAlign: 'center', padding: 48 }}>
          <Spin tip="加载校核表单…" />
        </div>
      ) : (
        <ReviewTaxonomyForm form={form} nodes={taxonomyNodes} aiLabelHints={review.ai_label_hints ?? {}} />
      )}
    </Modal>
  )
}
