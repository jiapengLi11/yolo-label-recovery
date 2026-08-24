export type Role = 'ADMIN' | 'REVIEWER' | 'AUDITOR'
export type Decision =
  | 'ACCEPT_ADD'
  | 'ACCEPT_REPLACE_GT'
  | 'ACCEPT_EVAL_LABEL'
  | 'REJECT'
  | 'UNCERTAIN'

export interface User {
  id: number
  username: string
  displayName: string
  role: Role
  enabled: boolean
}

export interface Project {
  id: number
  name: string
  description: string
  status: 'OPEN' | 'ARCHIVED'
  createdBy: string
  createdAt: string
}

export interface Progress {
  total: number
  pending: number
  claimed: number
  completed: number
  escalated: number
  completionRate: number
}

export interface ReviewTask {
  id: number
  version: number
  projectId: number
  candidateId: string
  split: string
  imageName: string
  className: string
  confidence: number
  caseCode: string
  recommendedAction: string
  state: string
  claimedBy: string
  leaseUntil: string
  visualUrl: string
}

const TOKEN_KEY = 'label-review-token'

export function token(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function saveToken(value: string): void {
  localStorage.setItem(TOKEN_KEY, value)
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY)
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  headers.set('Content-Type', 'application/json')
  const accessToken = token()
  if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`)
  const response = await fetch(path, { ...init, headers })
  if (response.status === 204) return undefined as T
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(body.detail || body.message || `请求失败 (${response.status})`)
  }
  return response.json() as Promise<T>
}

export async function login(username: string, password: string): Promise<{ accessToken: string; user: User }> {
  return request('/api/auth/login', { method: 'POST', body: JSON.stringify({ username, password }) })
}

export const api = {
  me: () => request<User>('/api/auth/me'),
  projects: () => request<Project[]>('/api/projects'),
  progress: (projectId: number) => request<Progress>(`/api/projects/${projectId}/progress`),
  claim: (projectId: number) => request<ReviewTask>(`/api/tasks/claim-next?projectId=${projectId}`, { method: 'POST' }),
  heartbeat: (taskId: number) => request<ReviewTask>(`/api/tasks/${taskId}/heartbeat`, { method: 'POST' }),
  release: (taskId: number) => request<void>(`/api/tasks/${taskId}/release`, { method: 'POST' }),
  decide: (task: ReviewTask, decision: Decision, comment: string) =>
    request<ReviewTask>(`/api/tasks/${task.id}/decision`, {
      method: 'POST',
      body: JSON.stringify({ decision, expectedVersion: task.version, comment }),
    }),
  users: () => request<User[]>('/api/admin/users'),
  createUser: (payload: { username: string; password: string; displayName: string; role: Role }) =>
    request<User>('/api/admin/users', { method: 'POST', body: JSON.stringify(payload) }),
  assignMember: (projectId: number, username: string) =>
    request(`/api/projects/${projectId}/members`, { method: 'POST', body: JSON.stringify({ username }) }),
}

export async function visualBlob(task: ReviewTask): Promise<string> {
  const response = await fetch(task.visualUrl, {
    headers: { Authorization: `Bearer ${token()}` },
  })
  if (!response.ok) throw new Error(`审核图加载失败 (${response.status})`)
  return URL.createObjectURL(await response.blob())
}
