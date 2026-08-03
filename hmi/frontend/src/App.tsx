import { App as AntApp, Spin } from 'antd'
import { lazy, Suspense } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AuthProvider } from './auth/AuthContext'
import { DataSourceProvider } from './context/DataSourceModeContext'
import { routerBasename } from './config/router'
import { RequireAuth } from './auth/RequireAuth'
import { RequireRole } from './auth/RequireRole'
import { STANDARD_ROLES } from './auth/roles'
import { AppLayout } from './layouts/AppLayout'
import { ReviewIndexRedirect, ReviewSectionLayout } from './layouts/ReviewSectionLayout'
import { AdminUsersPage } from './pages/AdminUsersPage'
import { AdminAuditPage } from './pages/AdminAuditPage'
import { SystemEnvPage } from './pages/SystemEnvPage'
import { LoginPage } from './pages/LoginPage'
import { RegisterPage } from './pages/RegisterPage'
import { OverviewPage } from './pages/OverviewPage'
import { OssManagePage } from './pages/OssManagePage'
import { ReviewAssignmentAdminPage } from './pages/ReviewAssignmentAdminPage'
import { ReviewAssignmentTasksPage } from './pages/ReviewAssignmentTasksPage'
import { ReviewConfidenceTasksPage } from './pages/ReviewDisputeTasksPage'
import { ReviewDetailRedirect, ReviewWorkbenchPage } from './pages/ReviewWorkbenchPage'
import { DatasetListPage } from './pages/DatasetListPage'
import { DatasetDetailPage } from './pages/DatasetDetailPage'
import { TaxonomyPage } from './pages/TaxonomyPage'

const ClipExplorerPage = lazy(() =>
  import('./pages/ClipExplorerPage').then((m) => ({ default: m.ClipExplorerPage })),
)
const PipelineManagePage = lazy(() =>
  import('./pages/PipelineManagePage').then((m) => ({ default: m.PipelineManagePage })),
)

export default function App() {
  return (
    <AntApp>
      <BrowserRouter basename={routerBasename()}>
        <AuthProvider>
          <DataSourceProvider>
            <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/register" element={<RegisterPage />} />
            <Route element={<RequireAuth />}>
              <Route element={<AppLayout />}>
                <Route index element={<OverviewPage />} />
                <Route element={<RequireRole roles={STANDARD_ROLES} />}>
                  <Route path="taxonomy" element={<TaxonomyPage />} />
                  <Route path="taxonomy/:versionId" element={<TaxonomyPage />} />
                  <Route path="clips/:clipId" element={
                    <Suspense fallback={<div style={{ textAlign: 'center', padding: 48 }}><Spin size="large" /></div>}>
                      <ClipExplorerPage />
                    </Suspense>
                  } />
                </Route>
                <Route element={<RequireRole roles={['admin', 'dataset_manager', 'pipeline_manager']} />}>
                  <Route path="pipeline" element={
                    <Suspense fallback={<div style={{ textAlign: 'center', padding: 48 }}><Spin size="large" /></div>}>
                      <PipelineManagePage />
                    </Suspense>
                  } />
                  <Route path="upload" element={<Navigate to="/pipeline" replace />} />
                </Route>
                <Route element={<RequireRole roles={['admin', 'dataset_manager']} />}>
                  <Route path="oss" element={<OssManagePage />} />
                </Route>
                <Route element={<RequireRole roles={['admin', 'reviewer']} />}>
                  <Route path="review" element={<ReviewSectionLayout />}>
                    <Route index element={<ReviewIndexRedirect />} />
                    <Route path="confidence" element={<ReviewConfidenceTasksPage />} />
                    <Route path="disputes" element={<Navigate to="/review/confidence" replace />} />
                    <Route path="tasks" element={<ReviewAssignmentTasksPage />} />
                    <Route element={<RequireRole roles={['admin']} />}>
                      <Route path="assignments" element={<ReviewAssignmentAdminPage />} />
                    </Route>
                  </Route>
                  <Route path="review/workbench" element={<ReviewWorkbenchPage />} />
                  <Route path="review/:clipId" element={<ReviewDetailRedirect />} />
                </Route>
                <Route
                  element={
                    <RequireRole roles={['admin', 'dataset_manager', 'model_trainer']} />
                  }
                >
                  <Route path="datasets" element={<DatasetListPage />} />
                  <Route path="datasets/:id" element={<DatasetDetailPage />} />
                </Route>
                <Route path="admin" element={<RequireRole roles={['admin']} />}>
                  <Route path="users" element={<AdminUsersPage />} />
                  <Route path="audit" element={<AdminAuditPage />} />
                  <Route path="system-env" element={<SystemEnvPage />} />
                </Route>
                <Route path="*" element={<Navigate to="/" replace />} />
              </Route>
            </Route>
          </Routes>
          </DataSourceProvider>
        </AuthProvider>
      </BrowserRouter>
    </AntApp>
  )
}
