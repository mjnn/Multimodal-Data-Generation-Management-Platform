import { App as AntApp } from 'antd'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AuthProvider } from './auth/AuthContext'
import { DemoModeProvider } from './context/DemoModeContext'
import { routerBasename } from './config/router'
import { RequireAuth } from './auth/RequireAuth'
import { RequireRole } from './auth/RequireRole'
import { AppLayout } from './layouts/AppLayout'
import { ReviewIndexRedirect, ReviewSectionLayout } from './layouts/ReviewSectionLayout'
import { AdminUsersPage } from './pages/AdminUsersPage'
import { ClipExplorerPage } from './pages/ClipExplorerPage'
import { LoginPage } from './pages/LoginPage'
import { OverviewPage } from './pages/OverviewPage'
import { OssManagePage } from './pages/OssManagePage'
import { ReviewAssignmentAdminPage } from './pages/ReviewAssignmentAdminPage'
import { ReviewAssignmentTasksPage } from './pages/ReviewAssignmentTasksPage'
import { ReviewConfidenceTasksPage } from './pages/ReviewDisputeTasksPage'
import { ReviewDetailRedirect, ReviewWorkbenchPage } from './pages/ReviewWorkbenchPage'
import { DatasetListPage } from './pages/DatasetListPage'
import { DatasetDetailPage } from './pages/DatasetDetailPage'
import { TaxonomyPage } from './pages/TaxonomyPage'

export default function App() {
  return (
    <AntApp>
      <BrowserRouter basename={routerBasename()}>
        <AuthProvider>
          <DemoModeProvider>
            <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route element={<RequireAuth />}>
              <Route element={<AppLayout />}>
                <Route index element={<OverviewPage />} />
                <Route path="taxonomy" element={<TaxonomyPage />} />
                <Route path="taxonomy/:versionId" element={<TaxonomyPage />} />
                <Route path="clips/:clipId" element={<ClipExplorerPage />} />
                <Route element={<RequireRole roles={['admin', 'dataset_manager']} />}>
                  <Route path="oss" element={<OssManagePage />} />
                  <Route path="upload" element={<Navigate to="/oss" replace />} />
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
                <Route element={<RequireRole roles={['admin']} />}>
                  <Route path="admin/users" element={<AdminUsersPage />} />
                </Route>
                <Route path="*" element={<Navigate to="/" replace />} />
              </Route>
            </Route>
          </Routes>
          </DemoModeProvider>
        </AuthProvider>
      </BrowserRouter>
    </AntApp>
  )
}
