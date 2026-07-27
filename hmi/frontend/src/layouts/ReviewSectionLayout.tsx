import { CheckCircleOutlined } from '@ant-design/icons'



import { Tabs } from 'antd'



import { Navigate, Outlet, useLocation, useNavigate } from 'react-router-dom'



import { useAuth } from '../auth/AuthContext'



import { canManageReviewAssignments } from '../auth/roles'



import { PageHeader, PageStack } from '../components/ui'



import { parseReviewV2OpenMode } from '../utils/reviewConfidence'







export function ReviewIndexRedirect() {



  const location = useLocation()



  const batch = new URLSearchParams(location.search).get('batch')



  const mode = new URLSearchParams(location.search).get('mode')



  if (batch) {



    return (



      <Navigate



        to={`/review/workbench?batch=${encodeURIComponent(batch)}`}



        replace



      />



    )



  }



  if (parseReviewV2OpenMode(mode)) {



    const normalized = mode === 'ai_dispute' ? 'confidence' : mode



    return <Navigate to={`/review/workbench?mode=${normalized}`} replace />



  }



  return <Navigate to="/review/confidence" replace />



}







export function ReviewSectionLayout() {



  const navigate = useNavigate()



  const location = useLocation()



  const { user } = useAuth()







  const tabItems = [



    { key: '/review/confidence', label: '置信度校核' },



    { key: '/review/tasks', label: '任务领取' },



  ]



  if (canManageReviewAssignments(user?.roles)) {



    tabItems.push({ key: '/review/assignments', label: '任务派发' })



  }







  const activeKey = location.pathname.startsWith('/review/assignments')



    ? '/review/assignments'



    : location.pathname.startsWith('/review/tasks')



      ? '/review/tasks'



      : '/review/confidence'







  return (



    <PageStack data-testid="review-section-layout">



      <PageHeader



        title="校核任务"



        description="置信度开放队列按空值与低置信度排序；管理员派发的任务包在「任务领取」中领取后进入工作台。"



        icon={<CheckCircleOutlined />}



      />







      <Tabs



        activeKey={activeKey}



        onChange={(key) => navigate(key)}



        items={tabItems}



        style={{ marginBottom: 0 }}



      />







      <Outlet />



    </PageStack>



  )



}



