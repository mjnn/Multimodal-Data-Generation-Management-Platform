export type AppRole = 'admin' | 'reviewer' | 'dataset_manager' | 'model_trainer'

export type AuthUser = {
  id: string
  username: string
  display_name: string
  roles: AppRole[]
  is_active: boolean
}

export type LoginResponse = {
  access_token: string
  token_type: string
  expires_in: number
  user: AuthUser
}
