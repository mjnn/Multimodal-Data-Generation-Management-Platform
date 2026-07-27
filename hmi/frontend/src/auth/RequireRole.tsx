import { Outlet } from 'react-router-dom'
import { useAuth } from './AuthContext'
import { ForbiddenPage } from '../pages/ForbiddenPage'
import type { AppRole } from './types'

type Props = {
  roles: AppRole[]
}

export function RequireRole({ roles }: Props) {
  const { user } = useAuth()
  const userRoles = user?.roles ?? []
  const allowed = roles.some((r) => userRoles.includes(r))
  if (!allowed) return <ForbiddenPage />
  return <Outlet />
}
