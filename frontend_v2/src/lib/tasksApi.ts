import { apiFetch, parseErrorBody } from './api'
import type {
  Task,
  TaskDetail,
  TaskDashboard,
  TaskComment,
  TaskCreatePayload,
  TaskPatchPayload,
  TaskListParams,
  TaskStatus,
} from '../ui/tasks/types'

const BASE = '/api/tasks'

export async function listTasks(params: TaskListParams = {}): Promise<Task[]> {
  const qs = new URLSearchParams()
  if (params.status) qs.set('status', params.status)
  if (params.assignee != null) qs.set('assignee', String(params.assignee))
  if (params.source_type) qs.set('source_type', params.source_type)
  if (params.include_all_done) qs.set('include_all_done', 'true')
  const url = qs.toString() ? `${BASE}/?${qs}` : `${BASE}/`
  const res = await apiFetch(url)
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as { results?: Task[] } | Task[] | null
  if (!json) return []
  return Array.isArray(json) ? json : (json.results ?? [])
}

export async function getTask(id: number): Promise<TaskDetail> {
  const res = await apiFetch(`${BASE}/${id}/`)
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as TaskDetail | null
  if (!json) throw new Error('Пустой ответ от сервера')
  return json
}

export async function createTask(payload: TaskCreatePayload): Promise<TaskDetail> {
  const res = await apiFetch(`${BASE}/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as TaskDetail | null
  if (!json) throw new Error('Пустой ответ от сервера')
  return json
}

export async function patchTask(id: number, payload: TaskPatchPayload): Promise<TaskDetail> {
  const res = await apiFetch(`${BASE}/${id}/`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as TaskDetail | null
  if (!json) throw new Error('Пустой ответ от сервера')
  return json
}

export async function changeTaskStatus(id: number, newStatus: TaskStatus): Promise<TaskDetail> {
  const res = await apiFetch(`${BASE}/${id}/status/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status: newStatus }),
  })
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as TaskDetail | null
  if (!json) throw new Error('Пустой ответ от сервера')
  return json
}

export async function deleteTask(id: number): Promise<void> {
  const res = await apiFetch(`${BASE}/${id}/`, { method: 'DELETE' })
  if (!res.ok) throw new Error(await parseErrorBody(res))
}

export async function remindTask(id: number): Promise<void> {
  const res = await apiFetch(`${BASE}/${id}/remind/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({}),
  })
  if (!res.ok) throw new Error(await parseErrorBody(res))
}

export async function addTaskComment(id: number, body: string): Promise<TaskComment> {
  const res = await apiFetch(`${BASE}/${id}/comments/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ body }),
  })
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as TaskComment | null
  if (!json) throw new Error('Пустой ответ от сервера')
  return json
}

export interface TasksConfig {
  tasks_webapp_url: string
}

export async function getTasksConfig(): Promise<TasksConfig> {
  const res = await apiFetch(`${BASE}/config/`)
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as TasksConfig | null
  return { tasks_webapp_url: json?.tasks_webapp_url ?? '' }
}

export async function patchTasksConfig(payload: Partial<TasksConfig>): Promise<TasksConfig> {
  const res = await apiFetch(`${BASE}/config/`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as TasksConfig | null
  if (!json) throw new Error('Пустой ответ от сервера')
  return json
}

export interface AssigneeCandidate {
  id: number
  username: string
}

export async function listAssigneeCandidates(): Promise<AssigneeCandidate[]> {
  const res = await apiFetch(`${BASE}/assignee-candidates/`)
  if (!res.ok) return []
  const json = (await res.json().catch(() => null)) as AssigneeCandidate[] | null
  return Array.isArray(json) ? json : []
}

export async function getTaskDashboard(): Promise<TaskDashboard> {
  const res = await apiFetch(`${BASE}/dashboard/`)
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as TaskDashboard | null
  if (!json) return { new: [], in_progress: [], done_recent: [] }
  return json
}
