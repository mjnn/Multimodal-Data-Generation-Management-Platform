import { Col, Empty, Modal, Row, Space, Spin, Typography } from 'antd'

import { useState } from 'react'

import { Link, Navigate, useSearchParams } from 'react-router-dom'

import { ReviewActionBar } from '../components/ReviewActionBar'

import { ReviewClipMediaPanel } from '../components/ReviewClipMediaPanel'

import { ReviewQueueOverview, ReviewQueueOverviewButton } from '../components/ReviewQueueOverview'

import { ReviewTaskPanel } from '../components/ReviewTaskPanel'

import { TaxonomyContextBar } from '../components/TaxonomyContextBar'
import { ContentCard, PageHeader, PageStack } from '../components/ui'

import { useReviewV2Session } from '../hooks/useReviewV2Session'

import { parseReviewV2OpenMode } from '../utils/reviewConfidence'



type WorkbenchVariant = 'batch' | 'confidence'



export function ReviewWorkbenchPage() {

  const [searchParams] = useSearchParams()

  const batchId = searchParams.get('batch')

  const mode = searchParams.get('mode')



  if (batchId) {

    return <ReviewWorkbenchContent variant="batch" batchId={batchId} />

  }

  if (parseReviewV2OpenMode(mode)) {

    return <ReviewWorkbenchContent variant="confidence" />

  }



  return <Navigate to="/review/confidence" replace />

}



function ReviewWorkbenchContent({

  variant,

  batchId,

}: {

  variant: WorkbenchVariant

  batchId?: string

}) {

  const isConfidenceMode = variant === 'confidence'

  const {

    task,

    currentStaged,

    queue,

    staged,

    queueTotal,

    stagedCount,

    allStaged,

    currentIndex,

    loading,

    committing,

    filterReady,

    loadPrev,

    loadNext,

    goToIndex,

    stage,

    commitQueue,

    canPrev,

    canNext,

    batchInfo,

  } = useReviewV2Session(isConfidenceMode ? null : batchId ?? null)



  const [overviewOpen, setOverviewOpen] = useState(false)



  const handleConfirm = () => {

    if (!task) return

    stage('confirm', task.ai_value)

  }



  const handleCorrect = (value: unknown) => {

    stage('correct', value)

  }



  const handleUncertain = () => {

    stage('uncertain', null)

  }



  const handleCommitQueue = () => {

    Modal.confirm({

      title: isConfidenceMode ? '确认提交本批校核？' : '确认提交本队列？',

      content: (

        <Space direction="vertical" size={8}>

          <span>

            将一次性提交 {queueTotal} 条暂存校核结果到服务器，提交后无法在本会话内撤回。

          </span>

          {!allStaged ? (

            <Typography.Text type="warning">

              当前仍有 {queueTotal - stagedCount} 条未暂存，请完成全部校核后再提交。

            </Typography.Text>

          ) : null}

        </Space>

      ),

      okText: '确认提交',

      cancelText: '取消',

      okButtonProps: { disabled: !allStaged },

      onOk: () => commitQueue(),

    })

  }



  const queueOverviewExtra = (

    <Space size={12}>

      <Typography.Text type="secondary">

        队列 {queueTotal} · 已暂存 {stagedCount}

        {allStaged && queueTotal > 0 ? ' · 可提交' : ''}

      </Typography.Text>

      <ReviewQueueOverviewButton

        disabled={!filterReady || queueTotal === 0}

        onClick={() => setOverviewOpen(true)}

      />

    </Space>

  )



  const title = isConfidenceMode

    ? '置信度优先校核'

    : batchInfo

      ? `校核：${batchInfo.name}`

      : '校核工作台'



  const description = isConfidenceMode

    ? '开放队列：空值与低置信度标签优先；逐条暂存，完成后统一提交。'

    : '任务包模式：逐条校核并暂存，整队列完成后统一确认提交。'



  const backTo = isConfidenceMode ? '/review/confidence' : '/review/tasks'

  const backLabel = isConfidenceMode ? '← 返回置信度校核' : '← 返回任务领取'



  return (

    <PageStack data-testid="review-workbench-page">

      <PageHeader

        title={title}

        description={description}

        extra={<Link to={backTo}>{backLabel}</Link>}

      />

      <TaxonomyContextBar />

      <ContentCard>

        <div

          style={{

            display: 'flex',

            justifyContent: 'flex-end',

            alignItems: 'center',

            marginBottom: 16,

          }}

        >

          {queueOverviewExtra}

        </div>



        <Spin spinning={loading}>

          {!filterReady ? (

            <Empty description="正在加载任务队列…" image={Empty.PRESENTED_IMAGE_SIMPLE} />

          ) : task ? (

            <Row gutter={16} align="top" className="review-workbench-layout">

              <Col xs={24} xl={15} className="review-workbench-layout__media">

                <ReviewClipMediaPanel task={task} />

              </Col>

              <Col xs={24} xl={9} className="review-workbench-layout__sidebar">

                <ReviewTaskPanel

                  task={task}

                  staged={currentStaged}

                  actions={

                    <ReviewActionBar

                      task={task}

                      canPrev={canPrev}

                      canNext={canNext}

                      loading={loading}

                      committing={committing}

                      allStaged={allStaged}

                      stagedCount={stagedCount}

                      queueTotal={queueTotal}

                      vertical

                      onConfirm={handleConfirm}

                      onCorrect={handleCorrect}

                      onUncertain={handleUncertain}

                      onPrev={loadPrev}

                      onNext={loadNext}

                      onCommitQueue={handleCommitQueue}

                    />

                  }

                />

              </Col>

            </Row>

          ) : (

            <Empty description="暂无待审任务" image={Empty.PRESENTED_IMAGE_SIMPLE} />

          )}

        </Spin>

      </ContentCard>



      <ReviewQueueOverview

        open={overviewOpen}

        queue={queue}

        staged={staged}

        currentIndex={currentIndex}

        onClose={() => setOverviewOpen(false)}

        onSelect={goToIndex}

      />

    </PageStack>

  )

}



/** Legacy detail route — redirect to confidence queue entry. */

export function ReviewDetailRedirect() {

  return <Navigate to="/review/confidence" replace />

}

