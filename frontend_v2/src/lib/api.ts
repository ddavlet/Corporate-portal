type Tokens = { access: string; refresh: string }

const STORAGE_KEY = 'kolberg_v2_tokens'

function getTokens(): Tokens | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as Partial<Tokens>
    if (!parsed.access || !parsed.refresh) return null
    return { access: parsed.access, refresh: parsed.refresh }
  } catch {
    return null
  }
}

function setTokens(tokens: Tokens | null) {
  if (!tokens) {
    localStorage.removeItem(STORAGE_KEY)
    return
  }
  localStorage.setItem(STORAGE_KEY, JSON.stringify(tokens))
}

async function refreshAccess(refresh: string): Promise<string | null> {
  const res = await fetch('/api/auth/token/refresh/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh }),
  })
  if (!res.ok) return null
  const data = (await res.json()) as { access?: string }
  return data.access ?? null
}

export async function apiFetch(input: string, init: RequestInit = {}) {
  const tokens = getTokens()
  const headers = new Headers(init.headers || {})
  headers.set('Accept', 'application/json')
  if (tokens?.access) headers.set('Authorization', `Bearer ${tokens.access}`)

  const doFetch = () =>
    fetch(input, {
      ...init,
      headers,
    })

  let res = await doFetch()

  // try refresh once
  if (res.status === 401 && tokens?.refresh) {
    const newAccess = await refreshAccess(tokens.refresh)
    if (newAccess) {
      setTokens({ access: newAccess, refresh: tokens.refresh })
      headers.set('Authorization', `Bearer ${newAccess}`)
      res = await doFetch()
    } else {
      setTokens(null)
    }
  }

  return res
}

export type CorporateCardExpense = {
  id: number
  title: string
  amount: string | number
  currency: string
  expense_at: string
  note: string
  payload?: Record<string, unknown>
  created_at: string
}

export type CorporateCardRevenue = {
  id: number
  external_id?: string
  revenue_date?: string | null
  confirmed?: boolean
  direction?: string
  organization?: string
  unit?: string
  employee?: string
  cash_type?: string
  operation?: string
  account?: string
  counterparty?: string
  total_sum?: string | number
  comment?: string
  source_year?: number | null
  title: string
  amount: string | number
  currency: string
  revenue_at: string
  note: string
  payload?: Record<string, unknown>
  bank_expense_id: number | null
  bank_expense_exists: boolean
  created_at: string
}

export type CashRevenue = {
  id: number
  title: string
  amount: string | number
  currency: string
  revenue_date: string | null
  category: string
  received_from: string
  payment_method: string
  reference_no: string
  status: string
  tags: unknown[]
  note: string
  payload?: Record<string, unknown>
  created_at: string
}

export type BankRevenue = {
  id: number
  row_no: number | null
  doc_date: string
  process_date: string
  doc_no: string
  account_name: string
  inn: string
  account_no: string
  mfo: string
  kredit_turnover: string | number
  payment_purpose: string
  created_at: string
}

function normalizeListPayload<T>(payload: unknown): T[] {
  if (Array.isArray(payload)) return payload as T[]
  if (payload && typeof payload === 'object' && 'results' in payload) {
    const results = (payload as { results?: unknown }).results
    return Array.isArray(results) ? (results as T[]) : []
  }
  return []
}

async function parseErrorBody(res: Response): Promise<string> {
  const json = await res.json().catch(() => null)
  return typeof json === 'object' && json ? JSON.stringify(json) : `HTTP ${res.status}`
}

export async function getCorporateCardExpenses(): Promise<CorporateCardExpense[]> {
  const res = await apiFetch('/api/corporate-card/expenses/')
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = await res.json().catch(() => null)
  return normalizeListPayload<CorporateCardExpense>(json)
}

export async function getCorporateCardRevenues(): Promise<CorporateCardRevenue[]> {
  const res = await apiFetch('/api/corporate-card/revenues/')
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = await res.json().catch(() => null)
  return normalizeListPayload<CorporateCardRevenue>(json)
}

export async function getCashRevenues(): Promise<CashRevenue[]> {
  const res = await apiFetch('/api/cash/revenues/')
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = await res.json().catch(() => null)
  return normalizeListPayload<CashRevenue>(json)
}

export async function getBankRevenues(): Promise<BankRevenue[]> {
  const res = await apiFetch('/api/bank/revenues/')
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = await res.json().catch(() => null)
  return normalizeListPayload<BankRevenue>(json)
}

export type RequestFormConfigCandidateUser = {
  id: number
  username: string
}

export type RequestFormConfigCandidateVendor = {
  id: number
  name: string
  account_number?: string | null
}

export type RequestFormConfigPurposeItem = {
  id?: number
  name: string
  category: string
  is_active?: boolean
}

export type RequestFormConfigPaymentTypeItem = {
  payment_type: string
  is_enabled: boolean
  requester_ids: number[]
  vendor_ids: number[]
  payment_purposes: RequestFormConfigPurposeItem[]
}

export type RequestFormConfigResponse = {
  payment_types: RequestFormConfigPaymentTypeItem[]
  requester_candidates: RequestFormConfigCandidateUser[]
  vendor_candidates: RequestFormConfigCandidateVendor[]
  category_candidates: string[]
}

export type RequestFormConfigUpdatePayload = {
  payment_types: Array<{
    payment_type: string
    is_enabled: boolean
    requester_ids: number[]
    vendor_ids: number[]
    payment_purposes: Array<{ name: string; category: string; is_active: boolean }>
  }>
}

export async function getRequestFormConfig(): Promise<RequestFormConfigResponse> {
  const res = await apiFetch('/api/requests/form-config/')
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as RequestFormConfigResponse | null
  if (!json) throw new Error('Empty response')
  return json
}

export async function updateRequestFormConfig(payload: RequestFormConfigUpdatePayload): Promise<RequestFormConfigResponse> {
  const res = await apiFetch('/api/requests/form-config/', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as RequestFormConfigResponse | null
  if (!json) throw new Error('Empty response')
  return json
}

