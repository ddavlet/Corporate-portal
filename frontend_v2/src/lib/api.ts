type Tokens = { access: string; refresh: string }

const STORAGE_KEY = 'kolberg_v2_tokens'
const TG_STORAGE_KEY = 'kolberg_v2_tg_tokens'
let unauthorizedHandler: (() => void) | null = null

function pathIsTgWebApp(): boolean {
  if (typeof window === 'undefined') return false
  return window.location.pathname.includes('/tg/')
}

function readPortalTokens(): Tokens | null {
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

function readPortalAuthState(): (Tokens & { username?: string }) | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as Partial<Tokens & { username: string }>
    if (!parsed.access || !parsed.refresh) return null
    return {
      access: parsed.access,
      refresh: parsed.refresh,
      ...(parsed.username ? { username: parsed.username } : {}),
    }
  } catch {
    return null
  }
}

export function readTgTokens(): Tokens | null {
  try {
    const raw = sessionStorage.getItem(TG_STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as Partial<Tokens>
    if (!parsed.access || !parsed.refresh) return null
    return { access: parsed.access, refresh: parsed.refresh }
  } catch {
    return null
  }
}

export function setTgTokens(tokens: Tokens | null) {
  if (!tokens) {
    sessionStorage.removeItem(TG_STORAGE_KEY)
    return
  }
  sessionStorage.setItem(TG_STORAGE_KEY, JSON.stringify(tokens))
}

export function setUnauthorizedHandler(handler: (() => void) | null) {
  unauthorizedHandler = handler
}

function getTokens(): Tokens | null {
  const tg = readTgTokens()
  const portal = readPortalTokens()
  if (pathIsTgWebApp()) {
    return tg ?? portal
  }
  return portal ?? tg
}

function setTokens(tokens: Tokens | null) {
  if (!tokens) {
    localStorage.removeItem(STORAGE_KEY)
    return
  }
  const prev = readPortalAuthState()
  localStorage.setItem(
    STORAGE_KEY,
    JSON.stringify({
      ...tokens,
      ...(prev?.username ? { username: prev.username } : {}),
    }),
  )
}

async function refreshAccess(refresh: string): Promise<Tokens | null> {
  const res = await fetch('/api/auth/token/refresh/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh }),
  })
  if (!res.ok) return null
  const data = (await res.json()) as { access?: string; refresh?: string }
  if (!data.access) return null
  return { access: data.access, refresh: data.refresh ?? refresh }
}

export type ApiFetchOptions = {
  /** When false, 401 does not clear tokens or call unauthorizedHandler (e.g. optional module endpoints). */
  treatAuthErrorsAsGlobal?: boolean
}

export async function apiFetch(input: string, init: RequestInit = {}, options?: ApiFetchOptions) {
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
    const refreshedTokens = await refreshAccess(tokens.refresh)
    if (refreshedTokens) {
      const next = refreshedTokens
      if (readTgTokens()?.refresh === tokens.refresh) setTgTokens(next)
      if (readPortalTokens()?.refresh === tokens.refresh) setTokens(next)
      headers.set('Authorization', `Bearer ${next.access}`)
      res = await doFetch()
    } else {
      if (readTgTokens()?.refresh === tokens.refresh) setTgTokens(null)
      if (readPortalTokens()?.refresh === tokens.refresh) setTokens(null)
    }
  }

  const globalAuth = options?.treatAuthErrorsAsGlobal !== false
  if (globalAuth && res.status === 401 && tokens?.access) {
    if (readTgTokens()?.refresh === tokens.refresh) setTgTokens(null)
    if (readPortalTokens()?.refresh === tokens.refresh) setTokens(null)
    unauthorizedHandler?.()
  }

  return res
}

export async function resendRequestApprovals(requestId: number): Promise<{ resent: number; pendingCurrentStep: number }> {
  const res = await apiFetch(`/api/requests/${requestId}/approvals/resend/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({}),
  })
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as { resent?: number; pending_current_step?: number } | null
  return {
    resent: Number(json?.resent ?? 0),
    pendingCurrentStep: Number(json?.pending_current_step ?? 0),
  }
}

export type TenantIntegrationConfigResponse = {
  telegram_bot_token: string
  telegram_approvals_bridge_dispatch_url: string
  telegram_approvals_send_action: string
  telegram_approvals_edit_action: string
  telegram_approvals_draft_notification_action: string
  telegram_approvals_message_template: string
  telegram_approvals_header_new_template: string
  telegram_approvals_header_step_approved_template: string
  telegram_approvals_header_fully_approved_template: string
  telegram_approvals_header_closed_template: string
  telegram_approvals_header_rejected_template: string
  telegram_approvals_subheader_payment_responsible_template: string
  telegram_approvals_subheader_rejected_by_template: string
  telegram_approvals_bridge_token: string
  n8n_integration_token: string
  requests_file_gateway_token: string
  portal_feedback_telegram_chat_id: number | null
  portal_feedback_telegram_action: string
}

export type TenantIntegrationConfigUpdatePayload = Partial<{
  telegram_bot_token: string
  telegram_approvals_bridge_dispatch_url: string
  telegram_approvals_send_action: string
  telegram_approvals_edit_action: string
  telegram_approvals_draft_notification_action: string
  telegram_approvals_message_template: string
  telegram_approvals_header_new_template: string
  telegram_approvals_header_step_approved_template: string
  telegram_approvals_header_fully_approved_template: string
  telegram_approvals_header_closed_template: string
  telegram_approvals_header_rejected_template: string
  telegram_approvals_subheader_payment_responsible_template: string
  telegram_approvals_subheader_rejected_by_template: string
  telegram_approvals_bridge_token: string
  n8n_integration_token: string
  requests_file_gateway_token: string
  portal_feedback_telegram_chat_id: number | null
  portal_feedback_telegram_action: string
}>

export type ModuleCatalogRow = {
  module_key: string
  display_name: string
  tenant_enabled: boolean
  user_allowed: boolean
  effective_enabled: boolean
}

export async function getModuleCatalog(): Promise<ModuleCatalogRow[]> {
  const res = await apiFetch('/api/modules/')
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as { modules?: ModuleCatalogRow[] } | null
  return Array.isArray(json?.modules) ? json.modules : []
}

export async function getTenantIntegrationConfig(): Promise<TenantIntegrationConfigResponse> {
  const res = await apiFetch('/api/tenant-integration-config/')
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as TenantIntegrationConfigResponse | null
  if (!json) throw new Error('Empty response')
  return json
}

export async function updateTenantIntegrationConfig(
  payload: TenantIntegrationConfigUpdatePayload,
): Promise<TenantIntegrationConfigResponse> {
  const res = await apiFetch('/api/tenant-integration-config/', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as TenantIntegrationConfigResponse | null
  if (!json) throw new Error('Empty response')
  return json
}

export type AccessMatrixUserRow = {
  user_id: number
  username: string
  full_name: string
  roles: string[]
  module_access: Record<string, boolean>
  tenant_settings_access: boolean
}

export type AccessMatrixResponse = {
  modules: Array<{ module_key: string; display_name: string }>
  users: AccessMatrixUserRow[]
}

export async function getAccessMatrix(): Promise<AccessMatrixResponse> {
  const res = await apiFetch('/api/access-matrix/')
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as AccessMatrixResponse | null
  if (!json) throw new Error('Empty response')
  return {
    modules: Array.isArray(json.modules) ? json.modules : [],
    users: Array.isArray(json.users) ? json.users : [],
  }
}

export type SettingsAccessResponse = {
  can_open_settings: boolean
  can_open_admin: boolean
  can_manage_tenant_settings: boolean
  can_manage_requests_settings: boolean
  can_manage_wallet_settings: boolean
  roles: string[]
}

export type UserPreferencesResponseItem = {
  key: string
  value: unknown
}

export async function getSettingsAccess(): Promise<SettingsAccessResponse> {
  const res = await apiFetch('/api/settings-access/')
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as Partial<SettingsAccessResponse> | null
  return {
    can_open_settings: Boolean(json?.can_open_settings),
    can_open_admin: Boolean(json?.can_open_admin),
    can_manage_tenant_settings: Boolean(json?.can_manage_tenant_settings),
    can_manage_requests_settings: Boolean(json?.can_manage_requests_settings),
    can_manage_wallet_settings: Boolean(json?.can_manage_wallet_settings),
    roles: Array.isArray(json?.roles) ? (json?.roles as string[]) : [],
  }
}

export async function getUserPreferences(keys: string[]): Promise<Record<string, unknown>> {
  if (!Array.isArray(keys) || keys.length === 0) return {}
  const params = new URLSearchParams()
  for (const key of keys) {
    const normalized = String(key || '').trim()
    if (normalized) params.append('keys', normalized)
  }
  const query = params.toString()
  const endpoint = query ? `/api/user-preferences/?${query}` : '/api/user-preferences/'
  const res = await apiFetch(endpoint)
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as { items?: UserPreferencesResponseItem[] } | null
  const out: Record<string, unknown> = {}
  const items = Array.isArray(json?.items) ? json.items : []
  for (const item of items) {
    if (item && typeof item.key === 'string') out[item.key] = item.value
  }
  return out
}

export async function setUserPreference(key: string, value: unknown): Promise<UserPreferencesResponseItem> {
  const normalized = String(key || '').trim()
  const res = await apiFetch(`/api/user-preferences/${encodeURIComponent(normalized)}/`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ value }),
  })
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as UserPreferencesResponseItem | null
  if (!json?.key) throw new Error('Empty response')
  return json
}

export type FeedbackKind = 'error' | 'improvement'

export type AskAiQuestionPayload = {
  question: string
  session_id?: string
}

export type AskAiQuestionResponse = {
  tenant_id?: number | string
  user_id?: number | string
  session_id: string
  response: string
  reponse?: string
  history?: Record<string, string>
}

export async function askAiQuestion(payload: AskAiQuestionPayload): Promise<AskAiQuestionResponse> {
  const question = String(payload.question || '').trim()
  if (!question) throw new Error('Вопрос не может быть пустым')
  const body: Record<string, string> = { question }
  if (payload.session_id && String(payload.session_id).trim()) {
    body.session_id = String(payload.session_id).trim()
  }

  const res = await apiFetch('/api/ai-questions/chat/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as Partial<AskAiQuestionResponse> | null
  const responseText = typeof json?.response === 'string' ? json.response : typeof json?.reponse === 'string' ? json.reponse : null
  if (!json?.session_id || !responseText) throw new Error('Пустой ответ от сервера')
  return {
    tenant_id: json.tenant_id,
    user_id: json.user_id,
    session_id: json.session_id,
    response: responseText,
    reponse: responseText,
    history: json.history,
  }
}

export async function refineFeedbackWithAi(payload: { kind: FeedbackKind; text: string }): Promise<{ feedback: string }> {
  const res = await apiFetch('/api/feedback/ai-refine/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ kind: payload.kind, text: payload.text }),
  })
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as { feedback?: string } | null
  if (!json?.feedback) throw new Error('Пустой ответ от сервера')
  return { feedback: json.feedback }
}

export async function submitFeedback(payload: {
  kind: FeedbackKind
  body: string
  page_path?: string
}): Promise<{ id: number; delivery: { status: string; error: string | null } }> {
  const res = await apiFetch('/api/feedback/submissions/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      kind: payload.kind,
      body: payload.body,
      page_path: payload.page_path ?? '',
    }),
  })
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as
    | { id?: number; delivery?: { status?: string; error?: string | null } }
    | null
  if (json?.id == null || !json.delivery?.status) throw new Error('Пустой ответ от сервера')
  return {
    id: json.id,
    delivery: { status: json.delivery.status, error: json.delivery.error ?? null },
  }
}

export async function changePassword(payload: {
  old_password?: string
  new_password: string
}): Promise<{ detail: string }> {
  const body: { old_password?: string; new_password: string } = { new_password: payload.new_password }
  if (payload.old_password != null && payload.old_password !== '') {
    body.old_password = payload.old_password
  }
  const res = await apiFetch('/api/auth/password/change/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const raw = await res.json().catch(() => null)
  if (!res.ok) {
    const detail =
      raw && typeof raw === 'object' && typeof (raw as { detail?: unknown }).detail === 'string'
        ? (raw as { detail: string }).detail
        : `HTTP ${res.status}`
    throw new Error(detail)
  }
  if (!raw || typeof raw !== 'object' || typeof (raw as { detail?: unknown }).detail !== 'string') {
    throw new Error('Пустой ответ от сервера')
  }
  return { detail: (raw as { detail: string }).detail }
}

export type CorporateCardExpense = {
  id: number
  title: string
  amount: string | number
  currency: string
  expense_at: string
  note: string
  has_request?: boolean
  has_paid_request?: boolean
  matched_request_id?: number | null
  request_required?: boolean
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
  external_id?: string
  revenue_at?: string | null
  currency: string
  confirmed?: boolean
  operation?: string
  wallet_id?: number | null
  counterparty?: string
  total_sum?: string | number
  comment?: string
  payload?: Record<string, unknown>
  created_at: string
}

export type ClientDebtSnapshot = {
  id: number
  snapshot_at: string
  doc_type: string
  organization: string
  client: string
  client_id: string
  debt_sum: string | number
  quantity: string | number
  cert_discount: string | number
  payload?: Record<string, unknown>
  created_at: string
  created_by: number
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

export type ApprovalDecision = 'approved' | 'rejected'

export type MyApprovalRequestSummary = {
  id: number
  title: string
  vendor?: string | null
  category?: string | null
  amount?: string | number | null
  currency?: string | null
  payment_type?: string | null
  urgency?: string | null
  status?: string | null
  submitted_at?: string | null
  billing_date?: string | null
  requester?: number | null
  requester_username?: string | null
}

export type MyApprovalStep = {
  id: number
  step: number
  step_type?: string | null
  payment_action_mode?: 'callback' | 'webapp' | string | null
  decision: string
  comment?: string | null
  decided_at?: string | null
}

export type MyApprovalGroup = {
  request: MyApprovalRequestSummary
  approvals: MyApprovalStep[]
}

export async function getMyApprovals(): Promise<MyApprovalGroup[]> {
  const res = await apiFetch('/api/requests/my-approvals/')
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as unknown
  return Array.isArray(json) ? (json as MyApprovalGroup[]) : []
}

export type RequestAuditMonthShiftsRow = {
  request_id: number
  vendor: string
  vendor_ref_id?: number | null
  category: string
  amount: string
  currency?: string | null
  payment_type?: string | null
  status?: string | null
  submitted_at?: string | null
  billing_month?: string | null
  expense_month?: string | null
  is_month_shifted: boolean
  amortization_months: number
  amortization_start_month?: string | null
  amort_prev?: string | null
  amort_current?: string | null
  amort_next?: string | null
}

export type RequestAuditMonthShiftsResponse = {
  months: { prev: string; current: string; next: string }
  rows: RequestAuditMonthShiftsRow[]
}

export async function getRequestAuditMonthShifts(month: string): Promise<RequestAuditMonthShiftsResponse> {
  const key = String(month || '').trim()
  const res = await apiFetch(`/api/requests/audit-month-shifts/?month=${encodeURIComponent(key)}`)
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as RequestAuditMonthShiftsResponse | null
  if (!json) throw new Error('Empty response')
  return {
    months: json.months,
    rows: Array.isArray(json.rows) ? json.rows : [],
  }
}

export async function setRequestApprovalDecision(payload: {
  requestId: number
  step: number
  decision: ApprovalDecision
  comment?: string
}): Promise<void> {
  const res = await apiFetch(`/api/requests/${payload.requestId}/approvals/decision/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      step: payload.step,
      decision: payload.decision,
      comment: payload.comment?.trim() || undefined,
    }),
  })
  if (!res.ok) throw new Error(await parseErrorBody(res))
}

export type LegacyReportItem = {
  id?: number | string
  date?: string
  amount?: number | string
  kredit?: number | string
  source?: string
  details?: string
  purpose?: string
  description?: string
  category?: string
  cathegory?: string
  cat?: string
  cat_name?: string
  article?: string
  item?: string
}

export type LegacyReportPayload = {
  revenue: LegacyReportItem[]
  expense: LegacyReportItem[]
  metadata?: Record<string, unknown>
}

function normalizeLegacyReportPayload(payload: unknown): LegacyReportPayload {
  const list = Array.isArray(payload) ? payload : payload && typeof payload === 'object' ? [payload] : []
  const revenue = list.find((x) => x && typeof x === 'object' && 'revenue' in x) as { revenue?: LegacyReportItem[] } | undefined
  const expense = list.find((x) => x && typeof x === 'object' && 'expense' in x) as { expense?: LegacyReportItem[] } | undefined
  const metadata = list.find((x) => x && typeof x === 'object' && 'metadata' in x) as { metadata?: Record<string, unknown> } | undefined
  return {
    revenue: Array.isArray(revenue?.revenue) ? revenue.revenue : [],
    expense: Array.isArray(expense?.expense) ? expense.expense : [],
    metadata: metadata?.metadata ?? {},
  }
}

export async function getPnlReportData(): Promise<LegacyReportPayload> {
  const res = await apiFetch('/api/reports/pnl/')
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = await res.json().catch(() => null)
  return normalizeLegacyReportPayload(json)
}

export async function getCashflowReportData(): Promise<LegacyReportPayload> {
  const res = await apiFetch('/api/reports/cashflow/')
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = await res.json().catch(() => null)
  return normalizeLegacyReportPayload(json)
}

export type StructuredReportRow = {
  id: string
  date: string | null
  amount: string
  direction: 'revenue' | 'expense'
  category?: string
  purpose: string
  description: string
  channel: string
  raw: Record<string, unknown>
}

export type StructuredMonthlyRow = {
  month: string
  revenue: string
  expense: string
  net: string
}

export type StructuredReportPayload = {
  report: 'pnl' | 'cashflow'
  metadata: {
    company_name?: string | null
    start_month?: string | null
    source?: string
    endpoint?: string
  }
  totals: {
    revenue: string
    expense: string
    net: string
  }
  monthly: StructuredMonthlyRow[]
  rows: StructuredReportRow[]
  revenue: LegacyReportItem[]
  expense: LegacyReportItem[]
}

function normalizeStructuredReportPayload(payload: unknown, report: 'pnl' | 'cashflow'): StructuredReportPayload {
  const obj = payload && typeof payload === 'object' ? (payload as Record<string, unknown>) : {}
  const metadata = obj.metadata && typeof obj.metadata === 'object' ? (obj.metadata as Record<string, unknown>) : {}
  const totals = obj.totals && typeof obj.totals === 'object' ? (obj.totals as Record<string, unknown>) : {}
  const monthly = Array.isArray(obj.monthly) ? (obj.monthly as StructuredMonthlyRow[]) : []
  const rows = Array.isArray(obj.rows) ? (obj.rows as StructuredReportRow[]) : []
  const revenue = Array.isArray(obj.revenue) ? (obj.revenue as LegacyReportItem[]) : []
  const expense = Array.isArray(obj.expense) ? (obj.expense as LegacyReportItem[]) : []
  return {
    report,
    metadata: {
      company_name: typeof metadata.company_name === 'string' ? metadata.company_name : null,
      start_month: typeof metadata.start_month === 'string' ? metadata.start_month : null,
      source: typeof metadata.source === 'string' ? metadata.source : undefined,
      endpoint: typeof metadata.endpoint === 'string' ? metadata.endpoint : undefined,
    },
    totals: {
      revenue: String(totals.revenue ?? '0'),
      expense: String(totals.expense ?? '0'),
      net: String(totals.net ?? '0'),
    },
    monthly,
    rows,
    revenue,
    expense,
  }
}

export async function getStructuredPnlReport(): Promise<StructuredReportPayload> {
  const res = await apiFetch('/api/reports/pnl/')
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = await res.json().catch(() => null)
  return normalizeStructuredReportPayload(json, 'pnl')
}

export async function getStructuredCashflowReport(): Promise<StructuredReportPayload> {
  const res = await apiFetch('/api/reports/cashflow/')
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = await res.json().catch(() => null)
  return normalizeStructuredReportPayload(json, 'cashflow')
}

export type TelegramWebAppAuthResponse = {
  access: string
  refresh: string
  username: string
}

export async function exchangeTelegramWebApp(initData: string): Promise<TelegramWebAppAuthResponse> {
  const res = await fetch('/api/auth/telegram/webapp/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify({ init_data: initData }),
  })
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as TelegramWebAppAuthResponse | null
  if (!json?.access || !json?.refresh) throw new Error('Empty auth response')
  return json
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

export async function getClientsDebtSnapshots(): Promise<ClientDebtSnapshot[]> {
  const res = await apiFetch('/api/clients-debt/')
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = await res.json().catch(() => null)
  return normalizeListPayload<ClientDebtSnapshot>(json)
}

/** Row from GET /api/cash|bank|corporate-card/balances/ */
export type ChannelBalanceRow = {
  wallet_id: number
  opening_balance: string
  movements_net: string
  current_balance: string
  currency: string
  prior_calendar_year?: number
  prior_calendar_year_net?: string
  cash_register_id?: number | null
  bank_account_id?: number | null
  corporate_card_account_id?: number | null
  display_name: string
  anchor_is_active: boolean
}

export async function getCashBalances(): Promise<ChannelBalanceRow[]> {
  const res = await apiFetch('/api/cash/balances/', {}, { treatAuthErrorsAsGlobal: false })
  if (res.status === 403) return []
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = await res.json().catch(() => null)
  return Array.isArray(json) ? (json as ChannelBalanceRow[]) : []
}

export async function getBankBalances(): Promise<ChannelBalanceRow[]> {
  const res = await apiFetch('/api/bank/balances/', {}, { treatAuthErrorsAsGlobal: false })
  if (res.status === 403) return []
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = await res.json().catch(() => null)
  return Array.isArray(json) ? (json as ChannelBalanceRow[]) : []
}

export async function getCorporateCardBalances(): Promise<ChannelBalanceRow[]> {
  const res = await apiFetch('/api/corporate-card/balances/', {}, { treatAuthErrorsAsGlobal: false })
  if (res.status === 403) return []
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = await res.json().catch(() => null)
  return Array.isArray(json) ? (json as ChannelBalanceRow[]) : []
}

export type CashRegisterDto = {
  id: number
  tenant: number
  currency: string
  name: string
  code: string
  description: string
  is_active: boolean
  sort_order: number
  is_default_for_currency: boolean
  wallet_id: number
}

export async function getCashRegisters(): Promise<CashRegisterDto[]> {
  const res = await apiFetch('/api/wallets/cash-registers/')
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = await res.json().catch(() => null)
  return normalizeListPayload<CashRegisterDto>(json)
}

export async function createCashRegister(payload: {
  currency: string
  name?: string
  code?: string
  description?: string
  is_active?: boolean
  sort_order?: number
  is_default_for_currency?: boolean
}): Promise<CashRegisterDto> {
  const res = await apiFetch('/api/wallets/cash-registers/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error(await parseErrorBody(res))
  return (await res.json()) as CashRegisterDto
}

export async function patchCashRegister(
  id: number,
  payload: Partial<{
    name: string
    code: string
    description: string
    is_active: boolean
    sort_order: number
    is_default_for_currency: boolean
  }>,
): Promise<CashRegisterDto> {
  const res = await apiFetch(`/api/wallets/cash-registers/${id}/`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error(await parseErrorBody(res))
  return (await res.json()) as CashRegisterDto
}

export async function deleteCashRegister(id: number): Promise<void> {
  const res = await apiFetch(`/api/wallets/cash-registers/${id}/`, { method: 'DELETE' })
  if (!res.ok) throw new Error(await parseErrorBody(res))
}

export type BankAccountDto = {
  id: number
  tenant: number
  label: string
  account_no: string
  mfo: string
  wallet_id: number
}

export async function getBankAccounts(): Promise<BankAccountDto[]> {
  const res = await apiFetch('/api/wallets/bank-accounts/')
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = await res.json().catch(() => null)
  return normalizeListPayload<BankAccountDto>(json)
}

export async function createBankAccount(payload: {
  label?: string
  account_no?: string
  mfo?: string
}): Promise<BankAccountDto> {
  const res = await apiFetch('/api/wallets/bank-accounts/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error(await parseErrorBody(res))
  return (await res.json()) as BankAccountDto
}

export async function patchBankAccount(
  id: number,
  payload: Partial<{ label: string; account_no: string; mfo: string }>,
): Promise<BankAccountDto> {
  const res = await apiFetch(`/api/wallets/bank-accounts/${id}/`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error(await parseErrorBody(res))
  return (await res.json()) as BankAccountDto
}

export async function deleteBankAccount(id: number): Promise<void> {
  const res = await apiFetch(`/api/wallets/bank-accounts/${id}/`, { method: 'DELETE' })
  if (!res.ok) throw new Error(await parseErrorBody(res))
}

export type CorporateCardAccountDto = {
  id: number
  tenant: number
  currency: string
  label: string
  external_ref: string
  wallet_id: number
}

export async function getCorporateCardAccounts(): Promise<CorporateCardAccountDto[]> {
  const res = await apiFetch('/api/wallets/corporate-card-accounts/')
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = await res.json().catch(() => null)
  return normalizeListPayload<CorporateCardAccountDto>(json)
}

export async function createCorporateCardAccount(payload: {
  currency: string
  label?: string
  external_ref?: string
}): Promise<CorporateCardAccountDto> {
  const res = await apiFetch('/api/wallets/corporate-card-accounts/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error(await parseErrorBody(res))
  return (await res.json()) as CorporateCardAccountDto
}

export async function patchCorporateCardAccount(
  id: number,
  payload: Partial<{ label: string; external_ref: string }>,
): Promise<CorporateCardAccountDto> {
  const res = await apiFetch(`/api/wallets/corporate-card-accounts/${id}/`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error(await parseErrorBody(res))
  return (await res.json()) as CorporateCardAccountDto
}

export async function deleteCorporateCardAccount(id: number): Promise<void> {
  const res = await apiFetch(`/api/wallets/corporate-card-accounts/${id}/`, { method: 'DELETE' })
  if (!res.ok) throw new Error(await parseErrorBody(res))
}

export type WalletDto = {
  id: number
  tenant: number
  wallet_type: string
  currency: string
  opening_balance: string
  opening_balance_at: string | null
  cash_register_id: number | null
  bank_account_id: number | null
  corporate_card_account_id: number | null
}

export async function patchWallet(
  id: number,
  payload: { opening_balance?: string; opening_balance_at?: string | null },
): Promise<WalletDto> {
  const res = await apiFetch(`/api/wallets/wallets/${id}/`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error(await parseErrorBody(res))
  return (await res.json()) as WalletDto
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
  kind: string
  name: string
  inn?: string | null
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
  default_title: string
  default_company_payer?: string
  default_description: string
  default_amount: string | null
  default_currency: string
  default_urgency: string
  default_billing_days_offset: number
  default_payment_purpose: string
  default_vendor_id: number | null
}

/** Месяц начисления относительно календарного месяца дня срабатывания шаблона. */
export type AutoRequestBillingMonthMode = 'previous' | 'current' | 'next'

export type AutoRequestTemplateItem = {
  id?: number
  is_enabled: boolean
  name: string
  payment_type: string
  day_of_month: number
  /** Предыдущий / этот / следующий месяц — подставляется в заявку и в токены шаблона заголовка/описания. */
  billing_month_mode?: AutoRequestBillingMonthMode
  title_template: string
  description_template: string
  amount: string | null
  currency: string
  urgency: string
  payment_purpose: string
  vendor_ref_id: number | null
  /** Заявитель в создаваемых заявках; должен быть из списка формы для выбранного типа оплаты. */
  requester_id?: number
  last_run_month?: string | null
}

export type AutoRequestConfigResponse = {
  templates: AutoRequestTemplateItem[]
  vendor_candidates: RequestFormConfigCandidateVendor[]
  /** Same shape as form-config payment_types: purposes, vendor_ids, default_company_payer per type */
  form_payment_types: RequestFormConfigPaymentTypeItem[]
  requester_candidates?: RequestFormConfigCandidateUser[]
}

export type AutoRequestConfigUpdatePayload = {
  templates: Array<{
    id?: number
    is_enabled: boolean
    name: string
    payment_type: string
    day_of_month: number
    billing_month_mode?: AutoRequestBillingMonthMode
    title_template: string
    description_template: string
    amount?: string | number | null
    currency?: string
    urgency?: string
    payment_purpose?: string
    vendor_ref_id?: number | null
    requester_id: number
  }>
}

export type RequestFormConfigResponse = {
  payment_types: RequestFormConfigPaymentTypeItem[]
  requester_candidates: RequestFormConfigCandidateUser[]
  vendor_candidates: RequestFormConfigCandidateVendor[]
  category_candidates: string[]
}

export type RequestFormConfigUpdatePayload = {
  /** Справочник категорий; при сохранении объединяется с категориями из назначений; неиспользуемые на бэкенде удаляются. */
  category_candidates?: string[]
  payment_types: Array<{
    payment_type: string
    is_enabled: boolean
    requester_ids: number[]
    vendor_ids: number[]
    payment_purposes: Array<{ name: string; category: string; is_active: boolean }>
    default_title?: string
    default_company_payer?: string
    default_description?: string
    default_amount?: string | number | null
    default_currency?: string
    default_urgency?: string
    default_billing_days_offset?: number
    default_payment_purpose?: string
    default_vendor_id?: number | null
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

export type CreateRequesterUserPayload = {
  username: string
  full_name: string
  telegram_chat_id?: number | null
  telegram_from_id?: number | null
}

export async function createRequesterUser(payload: CreateRequesterUserPayload): Promise<RequestFormConfigResponse> {
  const body: Record<string, unknown> = {
    username: payload.username,
    full_name: payload.full_name,
  }
  if (payload.telegram_chat_id != null) {
    body.telegram_chat_id = payload.telegram_chat_id
  }
  if (payload.telegram_from_id != null) {
    body.telegram_from_id = payload.telegram_from_id
  }
  const res = await apiFetch('/api/requests/form-config/requesters/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as RequestFormConfigResponse | null
  if (!json) throw new Error('Empty response')
  return json
}

export async function getAutoRequestConfig(): Promise<AutoRequestConfigResponse> {
  const res = await apiFetch('/api/requests/auto-config/')
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as AutoRequestConfigResponse | null
  if (!json) throw new Error('Empty response')
  return json
}

export async function updateAutoRequestConfig(payload: AutoRequestConfigUpdatePayload): Promise<AutoRequestConfigResponse> {
  const res = await apiFetch('/api/requests/auto-config/', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as AutoRequestConfigResponse | null
  if (!json) throw new Error('Empty response')
  return json
}

export type RequestApprovalConfigStepItem = {
  step: number
  step_type: string
  is_enabled: boolean
  approver_user_ids: number[]
  payment_action_mode?: 'callback' | 'webapp' | 'create'
  payment_webapp_url?: string
}

export type RequestApprovalConfigPaymentTypeItem = {
  payment_type: string
  is_enabled: boolean
  payment_action_mode_options?: Array<'callback' | 'webapp' | 'create' | string>
  request_not_required_field_options?: string[]
  request_not_required_rules?: Array<{ field: string; operator?: 'eq' | string; value: string }>
  steps: RequestApprovalConfigStepItem[]
}

export type RequestApprovalConfigResponse = {
  is_tenant_admin?: boolean
  payment_types: RequestApprovalConfigPaymentTypeItem[]
  approver_candidates: Array<{ id: number; username: string }>
  integration_settings?: {
    telegram_approvals_bridge_dispatch_url?: string
    telegram_approvals_send_action?: string
    telegram_approvals_edit_action?: string
    telegram_approvals_draft_notification_action?: string
    telegram_approvals_bridge_token?: string
    telegram_approvals_message_template?: string
    telegram_approvals_header_new_template?: string
    telegram_approvals_header_step_approved_template?: string
    telegram_approvals_header_fully_approved_template?: string
    telegram_approvals_header_closed_template?: string
    telegram_approvals_header_rejected_template?: string
    telegram_approvals_subheader_payment_responsible_template?: string
    telegram_approvals_subheader_rejected_by_template?: string
    n8n_integration_token?: string
  }
}

export type RequestApprovalConfigUpdatePayload = {
  payment_types: Array<{
    payment_type: string
    is_enabled: boolean
    request_not_required_rules?: Array<{ field: string; operator?: 'eq' | string; value: string }>
    steps: Array<{
      step: number
      step_type: string
      is_enabled: boolean
      approver_user_ids: number[]
      payment_action_mode?: 'callback' | 'webapp' | 'create'
      payment_webapp_url?: string
    }>
  }>
  integration_settings?: {
    telegram_approvals_bridge_dispatch_url?: string
    telegram_approvals_send_action?: string
    telegram_approvals_edit_action?: string
    telegram_approvals_draft_notification_action?: string
    telegram_approvals_bridge_token?: string
    telegram_approvals_message_template?: string
    telegram_approvals_header_new_template?: string
    telegram_approvals_header_step_approved_template?: string
    telegram_approvals_header_fully_approved_template?: string
    telegram_approvals_header_closed_template?: string
    telegram_approvals_header_rejected_template?: string
    telegram_approvals_subheader_payment_responsible_template?: string
    telegram_approvals_subheader_rejected_by_template?: string
    n8n_integration_token?: string
  }
}

export async function getRequestApprovalConfig(): Promise<RequestApprovalConfigResponse> {
  const res = await apiFetch('/api/requests/approval-config/')
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as RequestApprovalConfigResponse | null
  if (!json) throw new Error('Empty response')
  return json
}

export async function updateRequestApprovalConfig(
  payload: RequestApprovalConfigUpdatePayload,
): Promise<RequestApprovalConfigResponse> {
  const res = await apiFetch('/api/requests/approval-config/', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as RequestApprovalConfigResponse | null
  if (!json) throw new Error('Empty response')
  return json
}

export async function confirmPaymentViaWebApp(payload: {
  approval_id: number
  expense_id: string
}): Promise<{
  request: { id: number; status: string }
}> {
  const res = await apiFetch('/api/requests/approvals/payment-webapp/confirm/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as { request?: { id: number; status: string } } | null
  if (!json?.request) throw new Error('Empty response')
  return { request: json.request }
}

export type RequestFormOptionsRequester = {
  id: number
  username: string
}

export type RequestFormOptionsFormDefaults = {
  title: string
  description: string
  amount: string | null
  currency: string
  urgency: string
  billing_days_offset: number
  payment_purpose: string | null
  vendor_ref: number | null
}

export type RequestFormOptionsPaymentType = {
  payment_type: string
  requester_ids: number[]
  requesters: RequestFormOptionsRequester[]
  vendor_ids: number[]
  payment_purposes: Array<{ name: string; category: string }>
  defaults?: RequestFormOptionsFormDefaults
}

export type RequestFormOptionsResponse = {
  is_tenant_admin?: boolean
  requester_candidates?: RequestFormOptionsRequester[]
  payment_types: RequestFormOptionsPaymentType[]
}

export async function getRequestFormOptions(): Promise<RequestFormOptionsResponse> {
  const res = await apiFetch('/api/requests/form-options/')
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as RequestFormOptionsResponse | null
  if (!json) {
    return { is_tenant_admin: false, requester_candidates: [], payment_types: [] }
  }
  return {
    is_tenant_admin: json.is_tenant_admin ?? false,
    requester_candidates: json.requester_candidates ?? [],
    payment_types: json.payment_types ?? [],
  }
}

export type VendorDirectoryRow = {
  id: number
  tenant: number
  kind: string
  name: string
  inn?: string | null
  account_number?: string | null
  created_at: string
  created_by: number
}

export async function listVendors(params: { kind: 'cash' | 'transfer'; search?: string }): Promise<VendorDirectoryRow[]> {
  const sp = new URLSearchParams()
  sp.set('kind', params.kind)
  if (params.search?.trim()) sp.set('search', params.search.trim())
  const res = await apiFetch(`/api/vendors/?${sp.toString()}`)
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = await res.json().catch(() => null)
  return normalizeListPayload<VendorDirectoryRow>(json)
}

export type CreateVendorBody = {
  kind: 'cash' | 'transfer'
  name: string
  inn?: string
  account_number?: string
}

export async function createVendor(body: CreateVendorBody): Promise<VendorDirectoryRow> {
  const res = await apiFetch('/api/vendors/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as VendorDirectoryRow | null
  if (!json) throw new Error('Empty response')
  return json
}

/** Response from POST /api/requests/ (create). */
export interface CreatedPortalRequest {
  id: number
}

export type RequestAttachment = {
  id: number
  name: string
  content_type: string
  size_bytes: number
  created_at?: string
  url?: string | null
}

const REQUEST_ATTACHMENT_ALLOWED_EXT = new Set(['pdf', 'jpg', 'jpeg', 'png', 'doc', 'docx', 'xls', 'xlsx'])
export const REQUEST_ATTACHMENT_MAX_BYTES = 10 * 1024 * 1024
export const REQUEST_ATTACHMENT_MAX_FILES = 5

export function validateRequestAttachment(file: File): string | null {
  const ext = file.name.includes('.') ? file.name.split('.').pop()?.toLowerCase() || '' : ''
  if (!REQUEST_ATTACHMENT_ALLOWED_EXT.has(ext)) {
    return 'Недопустимый тип файла. Разрешены: pdf, jpg, jpeg, png, doc, docx, xls, xlsx.'
  }
  if (file.size > REQUEST_ATTACHMENT_MAX_BYTES) {
    return 'Файл превышает 10 МБ.'
  }
  return null
}

/** Body for POST /api/requests/ (portal create). */
export interface PortalRequestCreateBody {
  title: string
  description: string
  amount: number
  currency: string
  payment_type: string
  urgency: string
  billing_date: string
  status: string
  requester?: number
  payment_purpose?: string
  vendor_ref?: number
}

/** Insert a new request only (POST create). No update. */
export async function createPortalRequest(body: PortalRequestCreateBody): Promise<CreatedPortalRequest> {
  const res = await apiFetch('/api/requests/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as CreatedPortalRequest | null
  if (!json) throw new Error('Empty response')
  return json
}

export async function uploadRequestAttachment(requestId: number, file: File): Promise<RequestAttachment> {
  const fd = new FormData()
  fd.append('file', file)
  const res = await apiFetch(`/api/requests/${requestId}/file-upload/`, {
    method: 'POST',
    body: fd,
  })
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as Partial<RequestAttachment> | null
  return {
    id: Number(json?.id ?? 0),
    name: String(json?.name ?? file.name),
    content_type: String(json?.content_type ?? file.type ?? ''),
    size_bytes: Number(json?.size_bytes ?? file.size),
    created_at: typeof json?.created_at === 'string' ? json.created_at : undefined,
    url: typeof json?.url === 'string' ? json.url : null,
  }
}

export async function deleteRequestAttachment(requestId: number, attachmentId: number): Promise<void> {
  const res = await apiFetch(`/api/requests/${requestId}/attachments/${attachmentId}/`, {
    method: 'DELETE',
  })
  if (!res.ok) throw new Error(await parseErrorBody(res))
}

