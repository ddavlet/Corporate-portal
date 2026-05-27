export type TaskStatus = 'new' | 'in_progress' | 'done'

export type TaskSourceType =
  | 'manual'
  | 'approval_step'
  | 'request_approved'
  | 'payment_verify'
  | 'request_rejected'
  | 'escalation'

export interface TaskUser {
  id: number
  username: string
}

export interface TaskComment {
  id: number
  author: TaskUser | null
  body: string
  created_at: string
  is_admin_comment: boolean
}

export interface Task {
  id: number
  title: string
  status: TaskStatus
  source_type: TaskSourceType
  assignee: TaskUser | null
  created_by_id: number | null
  source_request_id: number | null
  source_approval_id: number | null
  created_at: string
  completed_at: string | null
  has_unseen_admin_comment: boolean
}

export interface TaskDetail extends Task {
  description: string
  created_by: TaskUser | null
  updated_at: string
  source_expense_type: string | null
  source_expense_id: number | null
  comments: TaskComment[]
}

export interface TaskDashboard {
  new: Task[]
  in_progress: Task[]
  done_recent: Task[]
}

export interface TaskCreatePayload {
  title: string
  description?: string
  assignee_id: number
  source_request_id?: number | null
  notify?: boolean
}

export interface TaskPatchPayload {
  title?: string
  description?: string
}

export interface TaskListParams {
  status?: TaskStatus
  assignee?: number
  source_type?: TaskSourceType
  include_all_done?: boolean
}
