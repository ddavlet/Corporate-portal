import { ApiError, apiFetch, parseErrorBody } from './api'
import { isSharedAppMode } from './portalMode'

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
  /**
   * Portal route without the /app prefix, e.g. "/requests/12" or "/investments?tab=returns&open=5". On the shared
   * app host it also carries `company=<subdomain>`, which switches the company when the link is opened.
   */
  link: string
  /** Company of the item: only in the all-companies answer of the shared app host. */
  tenant?: ActionItemTenant
}

export type ActionItemTenant = { subdomain: string; name: string }

export type ActionItemsResponse = {
  count: number
  items: ActionItem[]
}

/**
 * Stable identifier of an object, the same as the Web Push notification tag: `<kind>-<id>`, prefixed with the company
 * (`<subdomain>:<kind>-<id>`) for items of the all-companies answer.
 */
export function actionItemTag(item: Pick<ActionItem, 'kind' | 'id' | 'tenant'>): string {
  const tag = `${item.kind}-${item.id}`
  return item.tenant?.subdomain ? `${item.tenant.subdomain}:${tag}` : tag
}

export const ACTION_ITEMS_URL = '/api/notifications/action-items/'
export const ALL_ACTION_ITEMS_URL = '/api/notifications/action-items/all/'

/** Items of the current company (tenant subdomain). */
export function getActionItems(): Promise<ActionItemsResponse> {
  return fetchActionItems(ACTION_ITEMS_URL)
}

/** Items of all companies of the user, each with `tenant` (shared app host; needs no company). */
export function getAllActionItems(): Promise<ActionItemsResponse> {
  return fetchActionItems(ALL_ACTION_ITEMS_URL)
}

/** The endpoint for this portal mode: all companies on the shared app host, the current one on a subdomain. */
export function getActionItemsForPortal(): Promise<ActionItemsResponse> {
  return isSharedAppMode() ? getAllActionItems() : getActionItems()
}

async function fetchActionItems(url: string): Promise<ActionItemsResponse> {
  // Polled in the background: a failed poll shows no error toast, callers fall back to zero.
  const res = await apiFetch(url, {}, { silent: true })
  if (!res.ok) throw new ApiError(res.status, await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as Partial<ActionItemsResponse> | null
  const items = Array.isArray(json?.items) ? (json.items as ActionItem[]) : []
  const count = typeof json?.count === 'number' ? json.count : items.length
  return { count, items }
}
