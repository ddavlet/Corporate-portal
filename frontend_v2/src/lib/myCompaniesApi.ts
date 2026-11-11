import { ApiError, apiFetch, parseErrorBody } from './api'

/** A company of the signed-in user on the shared app host (GET /api/me/companies/). */
export type MyCompany = {
  subdomain: string
  name: string
  /** "Requires my action" items in this company when the list was read. */
  action_items_count: number
}

/** Active memberships in active companies, sorted by name on the server. Needs no company (no X-Tenant check). */
export async function getMyCompanies(): Promise<MyCompany[]> {
  const res = await apiFetch('/api/me/companies/', {}, { silent: true })
  if (!res.ok) throw new ApiError(res.status, await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as { companies?: unknown } | null
  const rows = Array.isArray(json?.companies) ? json.companies : []
  return rows
    .filter((row): row is Record<string, unknown> => Boolean(row) && typeof row === 'object')
    .map((row) => ({
      subdomain: String(row.subdomain ?? '').trim(),
      name: String(row.name ?? '').trim(),
      action_items_count: typeof row.action_items_count === 'number' ? row.action_items_count : 0,
    }))
    .filter((company) => company.subdomain)
}
