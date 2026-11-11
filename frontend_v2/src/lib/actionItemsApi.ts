import { ApiError, apiFetch, parseErrorBody } from './api'

export type ActionItemKind = 'request' | 'invest_return' | 'project_investment'

/** One object whose current approval step waits on the signed-in user (GET /api/notifications/action-items/). */
export type ActionItem = {
  kind: ActionItemKind
  id: number
  approval_id: number
  step: number
  step_type: string
  title: string
  /** Decimal as a string, e.g. "1500000.00". */
  amount: string
  currency: string
  type_code: string
  type_label: string
  created_at: string
  /** Portal route without the /app prefix, e.g. "/requests/12" or "/investments?tab=returns&open=5". */
  link: string
}

export type ActionItemsResponse = {
  count: number
  items: ActionItem[]
}

/** Stable identifier of an object, the same as the Web Push notification tag: `<kind>-<id>`. */
export function actionItemTag(item: Pick<ActionItem, 'kind' | 'id'>): string {
  return `${item.kind}-${item.id}`
}

export async function getActionItems(): Promise<ActionItemsResponse> {
  // Polled in the background: a failed poll shows no error toast, callers fall back to zero.
  const res = await apiFetch('/api/notifications/action-items/', {}, { silent: true })
  if (!res.ok) throw new ApiError(res.status, await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as Partial<ActionItemsResponse> | null
  const items = Array.isArray(json?.items) ? (json.items as ActionItem[]) : []
  const count = typeof json?.count === 'number' ? json.count : items.length
  return { count, items }
}
