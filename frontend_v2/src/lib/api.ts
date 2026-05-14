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
  /** For binary endpoints (file download): omit Accept: application/json. */
  omitAcceptJson?: boolean
}

export async function apiFetch(input: string, init: RequestInit = {}, options?: ApiFetchOptions) {
  const tokens = getTokens()
  const headers = new Headers(init.headers || {})
  if (!options?.omitAcceptJson) headers.set('Accept', 'application/json')
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
  const idempotencyKey = `resend:${requestId}:${Date.now()}:${Math.random().toString(36).slice(2, 10)}`
  const res = await apiFetch(`/api/requests/${requestId}/approvals/resend/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ idempotency_key: idempotencyKey }),
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
  telegram_bot_username: string
  telegram_oidc_client_id: string
  telegram_oidc_client_secret: string
  telegram_oidc_redirect_uri: string
  requests_file_gateway_token: string
  messaging_gateway_feedback_recipient_id: number | null
  messaging_gateway_feedback_action: string
  messaging_gateway_webhook_connected: boolean
  messaging_gateway_webhook_url: string
  messaging_gateway_webhook_error: string | null
}

export type TenantIntegrationConfigUpdatePayload = Partial<{
  telegram_bot_token: string
  telegram_bot_username: string
  telegram_oidc_client_id: string
  telegram_oidc_client_secret: string
  telegram_oidc_redirect_uri: string
  requests_file_gateway_token: string
  messaging_gateway_feedback_recipient_id: number | null
  messaging_gateway_feedback_action: string
}>

export type MessagingWebhookManageResponse = {
  ok: boolean
  connected?: boolean
  url?: string
  webhook_url?: string
  pending_update_count?: number
  last_error_message?: string | null
}

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

export type TenantCashExpenseIdFormatDto = {
  cash_expense_external_id_prefix: string
  cash_expense_external_id_digit_width: number
}

export async function getTenantCashExpenseIdFormat(): Promise<TenantCashExpenseIdFormatDto> {
  const res = await apiFetch('/api/tenant/cash-expense-id-format/')
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as TenantCashExpenseIdFormatDto | null
  if (!json) throw new Error('Empty response')
  return json
}

export async function updateTenantCashExpenseIdFormat(
  payload: TenantCashExpenseIdFormatDto,
): Promise<TenantCashExpenseIdFormatDto> {
  const res = await apiFetch('/api/tenant/cash-expense-id-format/', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as TenantCashExpenseIdFormatDto | null
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

export async function manageMessagingWebhook(
  action: 'set' | 'info' | 'delete',
  webhookUrl?: string,
): Promise<MessagingWebhookManageResponse> {
  const body: Record<string, unknown> = { action }
  if (webhookUrl && webhookUrl.trim()) body.webhook_url = webhookUrl.trim()
  const res = await apiFetch('/api/tenant-integration-config/messaging-webhook/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as MessagingWebhookManageResponse | null
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

export type AccessMatrixAssignmentPayload = {
  user_id: number
  roles: string[]
}

export async function updateAccessMatrixAssignments(
  assignments: AccessMatrixAssignmentPayload[],
): Promise<AccessMatrixResponse> {
  const res = await apiFetch('/api/access-matrix/', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ assignments }),
  })
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as AccessMatrixResponse | null
  if (!json) throw new Error('Empty response')
  return {
    modules: Array.isArray(json.modules) ? json.modules : [],
    users: Array.isArray(json.users) ? json.users : [],
  }
}

export type SettingsAccessResponse = {
  tenant_name?: string
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
    tenant_name: typeof json?.tenant_name === 'string' ? json.tenant_name : undefined,
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

export type FeedbackWorkStatus = 'new' | 'in_progress' | 'done'

export type MyFeedbackItem = {
  id: number
  kind: FeedbackKind
  body: string
  page_path: string
  work_status: FeedbackWorkStatus
  work_status_label: string
  created_at: string
  resolved_at: string | null
}

export async function listMyFeedback(): Promise<MyFeedbackItem[]> {
  const res = await apiFetch('/api/feedback/my/', { method: 'GET' })
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as { results?: MyFeedbackItem[] } | null
  return Array.isArray(json?.results) ? json.results : []
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
  operational_expenses: LegacyReportItem[]
  other_expenses: LegacyReportItem[]
  expense: LegacyReportItem[]
  invest_returns: LegacyReportItem[]
  metadata?: Record<string, unknown>
}

function normalizeLegacyReportPayload(payload: unknown): LegacyReportPayload {
  const list = Array.isArray(payload) ? payload : payload && typeof payload === 'object' ? [payload] : []
  const revenue = list.find((x) => x && typeof x === 'object' && 'revenue' in x) as { revenue?: LegacyReportItem[] } | undefined
  const operationalExpenses = list.find((x) => x && typeof x === 'object' && 'operational_expenses' in x) as
    | { operational_expenses?: LegacyReportItem[] }
    | undefined
  const otherExpenses = list.find((x) => x && typeof x === 'object' && 'other_expenses' in x) as
    | { other_expenses?: LegacyReportItem[] }
    | undefined
  const expense = list.find((x) => x && typeof x === 'object' && 'expense' in x) as { expense?: LegacyReportItem[] } | undefined
  const investReturns = list.find((x) => x && typeof x === 'object' && 'invest_returns' in x) as
    | { invest_returns?: LegacyReportItem[] }
    | undefined
  const metadata = list.find((x) => x && typeof x === 'object' && 'metadata' in x) as { metadata?: Record<string, unknown> } | undefined
  return {
    revenue: Array.isArray(revenue?.revenue) ? revenue.revenue : [],
    operational_expenses: Array.isArray(operationalExpenses?.operational_expenses) ? operationalExpenses.operational_expenses : [],
    other_expenses: Array.isArray(otherExpenses?.other_expenses) ? otherExpenses.other_expenses : [],
    expense: Array.isArray(expense?.expense) ? expense.expense : [],
    invest_returns: Array.isArray(investReturns?.invest_returns) ? investReturns.invest_returns : [],
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

/** Rules for backend PnL (also returned in structured report as report_settings). */
export type PnlReportSettingsSnapshot = {
  start_month?: string
  cash_exclude_operations?: string[]
  request_exclude_categories?: string[]
  request_payment_types_for_pnl?: string[]
  payment_purpose_operational?: string[]
  payment_purpose_other?: string[]
  payment_purpose_invest_returns?: string[]
  invest_return_type_operational?: string[]
  invest_return_type_other?: string[]
  invest_return_type_invest_returns?: string[]
}

export type PnlDiagnosticsItem = { purpose: string; count: number }

export type PnlDiagnosticsApi = {
  unassigned_payment_purposes?: PnlDiagnosticsItem[]
  error?: string
}

export type TenantReportSettingsApiResponse = {
  pnl_source: 'n8n' | 'backend'
  pnl_config: PnlReportSettingsSnapshot
  updated_at?: string | null
  pnl_diagnostics?: PnlDiagnosticsApi
}

function parseTenantReportSettingsApiResponse(json: unknown): TenantReportSettingsApiResponse {
  const obj = json && typeof json === 'object' ? (json as Record<string, unknown>) : {}
  const src = String(obj.pnl_source || '').toLowerCase()
  const pnl_source: 'n8n' | 'backend' = src === 'backend' ? 'backend' : 'n8n'
  const rawCfg = obj.pnl_config
  const pnl_config: PnlReportSettingsSnapshot =
    rawCfg && typeof rawCfg === 'object' ? (rawCfg as PnlReportSettingsSnapshot) : {}
  const rawDiag = obj.pnl_diagnostics
  const pnl_diagnostics: PnlDiagnosticsApi | undefined =
    rawDiag && typeof rawDiag === 'object' ? (rawDiag as PnlDiagnosticsApi) : undefined
  return {
    pnl_source,
    pnl_config,
    updated_at: typeof obj.updated_at === 'string' ? obj.updated_at : null,
    pnl_diagnostics,
  }
}

export async function getTenantReportSettings(opts?: {
  pnlDiagnostics?: boolean
}): Promise<TenantReportSettingsApiResponse> {
  const q = opts?.pnlDiagnostics ? '?pnl_diagnostics=1' : ''
  const res = await apiFetch(`/api/reports/tenant-report-settings/${q}`)
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const parsedJson: unknown = await res.json().catch(() => null)
  return parseTenantReportSettingsApiResponse(parsedJson)
}

export async function patchTenantReportSettings(
  payload: Partial<{ pnl_source: 'n8n' | 'backend'; pnl_config: PnlReportSettingsSnapshot }>,
): Promise<TenantReportSettingsApiResponse> {
  const res = await apiFetch('/api/reports/tenant-report-settings/', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const parsedJson: unknown = await res.json().catch(() => null)
  return parseTenantReportSettingsApiResponse(parsedJson)
}

export type TenantPnlPaymentPurposePoolResponse = {
  purposes: string[]
}

function parseTenantPnlPaymentPurposePoolResponse(json: unknown): TenantPnlPaymentPurposePoolResponse {
  const obj = json && typeof json === 'object' ? (json as Record<string, unknown>) : {}
  const raw = obj.purposes
  const purposes: string[] = []
  if (Array.isArray(raw)) {
    for (const x of raw) {
      const s = String(x ?? '').trim()
      if (s) purposes.push(s)
    }
  }
  purposes.sort((a, b) => a.localeCompare(b, 'ru'))
  return { purposes }
}

export async function getTenantPnlPaymentPurposePool(): Promise<TenantPnlPaymentPurposePoolResponse> {
  const res = await apiFetch('/api/reports/payment-purpose-pool/')
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const parsedJson: unknown = await res.json().catch(() => null)
  return parseTenantPnlPaymentPurposePoolResponse(parsedJson)
}

export type StructuredReportPayload = {
  report: 'pnl' | 'cashflow'
  metadata: {
    company_name?: string | null
    start_month?: string | null
    source?: string
    endpoint?: string
  }
  /** Backend PnL: filters and period from tenant_report_settings (read-only). */
  report_settings?: PnlReportSettingsSnapshot | null
  totals: {
    revenue: string
    operational_expense?: string
    other_expense?: string
    expense: string
    ebit?: string
    net: string
    invest_returns?: string
    balance?: string
  }
  monthly: StructuredMonthlyRow[]
  rows: StructuredReportRow[]
  revenue: LegacyReportItem[]
  operational_expenses: LegacyReportItem[]
  other_expenses: LegacyReportItem[]
  expense: LegacyReportItem[]
  invest_returns: LegacyReportItem[]
}

function normalizeStructuredReportPayload(payload: unknown, report: 'pnl' | 'cashflow'): StructuredReportPayload {
  const obj = payload && typeof payload === 'object' ? (payload as Record<string, unknown>) : {}
  const metadata = obj.metadata && typeof obj.metadata === 'object' ? (obj.metadata as Record<string, unknown>) : {}
  const totals = obj.totals && typeof obj.totals === 'object' ? (obj.totals as Record<string, unknown>) : {}
  const monthly = Array.isArray(obj.monthly) ? (obj.monthly as StructuredMonthlyRow[]) : []
  const rows = Array.isArray(obj.rows) ? (obj.rows as StructuredReportRow[]) : []
  const revenue = Array.isArray(obj.revenue) ? (obj.revenue as LegacyReportItem[]) : []
  const operationalExpenses = Array.isArray(obj.operational_expenses) ? (obj.operational_expenses as LegacyReportItem[]) : []
  const otherExpenses = Array.isArray(obj.other_expenses) ? (obj.other_expenses as LegacyReportItem[]) : []
  const expense = Array.isArray(obj.expense) ? (obj.expense as LegacyReportItem[]) : []
  const investReturns = Array.isArray(obj.invest_returns) ? (obj.invest_returns as LegacyReportItem[]) : []
  const reportSettingsRaw = obj.report_settings
  const report_settings =
    reportSettingsRaw && typeof reportSettingsRaw === 'object'
      ? (reportSettingsRaw as PnlReportSettingsSnapshot)
      : null
  return {
    report,
    metadata: {
      company_name: typeof metadata.company_name === 'string' ? metadata.company_name : null,
      start_month: typeof metadata.start_month === 'string' ? metadata.start_month : null,
      source: typeof metadata.source === 'string' ? metadata.source : undefined,
      endpoint: typeof metadata.endpoint === 'string' ? metadata.endpoint : undefined,
    },
    report_settings,
    totals: {
      revenue: String(totals.revenue ?? '0'),
      operational_expense: totals.operational_expense != null ? String(totals.operational_expense) : undefined,
      other_expense: totals.other_expense != null ? String(totals.other_expense) : undefined,
      expense: String(totals.expense ?? '0'),
      ebit: totals.ebit != null ? String(totals.ebit) : undefined,
      net: String(totals.net ?? '0'),
      invest_returns: totals.invest_returns != null ? String(totals.invest_returns) : undefined,
      balance: totals.balance != null ? String(totals.balance) : undefined,
    },
    monthly,
    rows,
    revenue,
    operational_expenses: operationalExpenses,
    other_expenses: otherExpenses,
    expense,
    invest_returns: investReturns,
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

// ─── Investments module ──────────────────────────────────────────────────────

export type InvestCompanyRow = {
  id: number
  name: string
  comment: string
  is_active: boolean
  created_at: string
}

export type ProjectInvestmentRow = {
  id: number
  company: number | null
  date: string
  amount: string | number
  currency: string
  comment: string
  confirmed: boolean
  created_at: string
}

export type InvestPayoutScheduleRow = {
  id: number
  company: number | null
  payout_date: string
  amount: string | number
  currency: string
  is_paid: boolean
  payment_amount: string | number
  comment: string
  created_at: string
}

export type InvestPayoutScheduleShareLinkRow = {
  id: number
  token: string
  company: number | null
  paid_filter: 'all' | 'paid' | 'unpaid'
  is_active: boolean
  created_at: string
  created_by: number
}

export type CreateInvestPayoutScheduleShareLinkPayload = {
  company?: number | null
  paid_filter: 'all' | 'paid' | 'unpaid'
}

export type PublicInvestPayoutScheduleRow = {
  id: number
  payout_date: string
  amount: string | number
  is_paid: boolean
  payment_amount: string | number
  comment: string
  company: number | null
  company_name: string
  currency: string
}

export type PublicInvestPayoutScheduleResponse = {
  filters: {
    company: number | null
    company_name: string
    tenant_name: string
    paid_filter: 'all' | 'paid' | 'unpaid'
  }
  rows: PublicInvestPayoutScheduleRow[]
}

export type InvestReturnRow = {
  id: number
  company: number | null
  date: string
  billing_date: string
  sum: string | number
  sum_uzs?: string | number | null
  cbu_usd_uzs_rate?: string | number | null
  currency: string
  confirmed: boolean
  type: string
  recipient: string
  comment: string
  created_at: string
}

export type CreateInvestReturnPayload = {
  company?: number | null
  date: string
  billing_date: string
  sum: string | number
  comment?: string
  currency: string
  type: string
  recipient: string
}

export type InvestmentApprovalConfigStepItem = {
  step: number
  step_type: 'serial' | 'confirmation' | 'notification'
  is_enabled: boolean
  payment_chat_id?: number | null
  approver_user_ids: number[]
}

export type InvestmentReturnTypeChoice = { value: string; label: string }

export type InvestmentApprovalConfigResponse = {
  return_type: string | null
  recipient: string | null
  return_type_choices: InvestmentReturnTypeChoice[]
  recipient_choices: InvestmentReturnTypeChoice[]
  is_enabled: boolean
  steps: InvestmentApprovalConfigStepItem[]
  approver_candidates: Array<{ id: number; username: string }>
}

export type InvestmentProjectApprovalConfigResponse = {
  is_enabled: boolean
  steps: InvestmentApprovalConfigStepItem[]
  approver_candidates: Array<{ id: number; username: string }>
}

export type InvestmentFormConfigResponse = {
  uses_companies: boolean
  allowed_return_types: string[]
  return_type_choices: InvestmentReturnTypeChoice[]
}

/** Fallback when form-config API fails — mirrors backend InvestReturn.ReturnType. */
export const DEFAULT_INVESTMENT_FORM_CONFIG: InvestmentFormConfigResponse = {
  uses_companies: true,
  allowed_return_types: ['дивиденды', 'проценты', 'доля_прибыли', 'тело_инвестиций'],
  return_type_choices: [
    { value: 'дивиденды', label: 'Дивиденды' },
    { value: 'проценты', label: 'Проценты' },
    { value: 'доля_прибыли', label: 'Доля прибыли' },
    { value: 'тело_инвестиций', label: 'Тело инвестиций' },
  ],
}

export async function getInvestCompanies(): Promise<InvestCompanyRow[]> {
  const res = await apiFetch('/api/investments/companies/')
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = await res.json().catch(() => null)
  return normalizeListPayload<InvestCompanyRow>(json)
}

export async function getProjectInvestments(): Promise<ProjectInvestmentRow[]> {
  const res = await apiFetch('/api/investments/project-investments/')
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = await res.json().catch(() => null)
  return normalizeListPayload<ProjectInvestmentRow>(json)
}

export async function getInvestPayoutSchedule(): Promise<InvestPayoutScheduleRow[]> {
  const res = await apiFetch('/api/investments/payout-schedule/')
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = await res.json().catch(() => null)
  return normalizeListPayload<InvestPayoutScheduleRow>(json)
}

export async function getInvestPayoutScheduleShareLinks(): Promise<InvestPayoutScheduleShareLinkRow[]> {
  const res = await apiFetch('/api/investments/payout-schedule-share-links/')
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = await res.json().catch(() => null)
  return normalizeListPayload<InvestPayoutScheduleShareLinkRow>(json)
}

export async function createInvestPayoutScheduleShareLink(
  payload: CreateInvestPayoutScheduleShareLinkPayload,
): Promise<InvestPayoutScheduleShareLinkRow> {
  const body: Record<string, unknown> = { paid_filter: payload.paid_filter }
  if (payload.company !== undefined) body.company = payload.company
  const res = await apiFetch('/api/investments/payout-schedule-share-links/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as InvestPayoutScheduleShareLinkRow | null
  if (!json) throw new Error('Empty response')
  return json
}

export async function deleteInvestPayoutScheduleShareLink(id: number): Promise<void> {
  const res = await apiFetch(`/api/investments/payout-schedule-share-links/${id}/`, { method: 'DELETE' })
  if (!res.ok) throw new Error(await parseErrorBody(res))
}

export async function getPublicInvestPayoutSchedule(token: string): Promise<PublicInvestPayoutScheduleResponse> {
  const res = await fetch(`/api/investments/public/payout-schedule/${encodeURIComponent(token)}/`, {
    headers: { Accept: 'application/json' },
  })
  const json = (await res.json().catch(() => null)) as PublicInvestPayoutScheduleResponse | { detail?: string } | null
  if (!res.ok) {
    const detail =
      json && typeof json === 'object' && 'detail' in json && typeof (json as { detail?: unknown }).detail === 'string'
        ? (json as { detail: string }).detail
        : `HTTP ${res.status}`
    throw new Error(detail)
  }
  if (!json || !('rows' in json) || !Array.isArray(json.rows)) throw new Error('Empty response')
  return json
}

export async function getInvestReturns(): Promise<InvestReturnRow[]> {
  const res = await apiFetch('/api/investments/returns/')
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = await res.json().catch(() => null)
  return normalizeListPayload<InvestReturnRow>(json)
}

export async function createInvestReturn(payload: CreateInvestReturnPayload): Promise<InvestReturnRow> {
  const body: Record<string, unknown> = {
    date: payload.date,
    billing_date: payload.billing_date,
    sum: payload.sum,
    currency: payload.currency,
    type: payload.type,
    recipient: payload.recipient,
    confirmed: false,
    comment: payload.comment ?? '',
  }
  if (payload.company !== undefined) body.company = payload.company
  const res = await apiFetch('/api/investments/returns/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as InvestReturnRow | null
  if (!json) throw new Error('Empty response')
  return json
}

export type CreateInvestCompanyPayload = {
  name: string
  comment?: string
  is_active?: boolean
}

export async function createInvestCompany(payload: CreateInvestCompanyPayload): Promise<InvestCompanyRow> {
  const body: Record<string, unknown> = {
    name: payload.name,
    comment: payload.comment ?? '',
    is_active: payload.is_active ?? true,
  }
  const res = await apiFetch('/api/investments/companies/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as InvestCompanyRow | null
  if (!json) throw new Error('Empty response')
  return json
}

export type CreateProjectInvestmentPayload = {
  company?: number | null
  date: string
  amount: string | number
  currency: string
  comment?: string
}

export async function createProjectInvestment(payload: CreateProjectInvestmentPayload): Promise<ProjectInvestmentRow> {
  const body: Record<string, unknown> = {
    date: payload.date,
    amount: payload.amount,
    currency: payload.currency,
    comment: payload.comment ?? '',
  }
  if (payload.company !== undefined) body.company = payload.company
  const res = await apiFetch('/api/investments/project-investments/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as ProjectInvestmentRow | null
  if (!json) throw new Error('Empty response')
  return json
}

export type CreateInvestPayoutSchedulePayload = {
  company?: number | null
  payout_date: string
  amount: string | number
  currency: string
  comment?: string
  is_paid?: boolean
  payment_amount?: string | number
}

export async function createInvestPayoutSchedule(
  payload: CreateInvestPayoutSchedulePayload,
): Promise<InvestPayoutScheduleRow> {
  const body: Record<string, unknown> = {
    payout_date: payload.payout_date,
    amount: payload.amount,
    currency: payload.currency,
    comment: payload.comment ?? '',
    is_paid: payload.is_paid ?? false,
    payment_amount: payload.payment_amount ?? '0',
  }
  if (payload.company !== undefined) body.company = payload.company
  const res = await apiFetch('/api/investments/payout-schedule/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as InvestPayoutScheduleRow | null
  if (!json) throw new Error('Empty response')
  return json
}

export async function getInvestmentApprovalConfig(
  returnType?: string | null,
  recipient?: string | null,
): Promise<InvestmentApprovalConfigResponse> {
  const params = new URLSearchParams()
  if (returnType != null && returnType !== '') params.set('return_type', returnType)
  if (recipient != null && recipient !== '') params.set('recipient', recipient)
  const qs = params.toString()
  const url = qs ? `/api/investments/approval-config/?${qs}` : '/api/investments/approval-config/'
  const res = await apiFetch(url)
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as InvestmentApprovalConfigResponse | null
  if (!json) throw new Error('Empty response')
  return json
}

export async function updateInvestmentApprovalConfig(
  payload: Pick<InvestmentApprovalConfigResponse, 'is_enabled' | 'steps' | 'return_type' | 'recipient'>,
): Promise<InvestmentApprovalConfigResponse> {
  const res = await apiFetch('/api/investments/approval-config/', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as InvestmentApprovalConfigResponse | null
  if (!json) throw new Error('Empty response')
  return json
}

export async function getInvestmentProjectApprovalConfig(): Promise<InvestmentProjectApprovalConfigResponse> {
  const res = await apiFetch('/api/investments/project-approval-config/')
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as InvestmentProjectApprovalConfigResponse | null
  if (!json) throw new Error('Empty response')
  return json
}

export async function updateInvestmentProjectApprovalConfig(
  payload: Pick<InvestmentProjectApprovalConfigResponse, 'is_enabled' | 'steps'>,
): Promise<InvestmentProjectApprovalConfigResponse> {
  const res = await apiFetch('/api/investments/project-approval-config/', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as InvestmentProjectApprovalConfigResponse | null
  if (!json) throw new Error('Empty response')
  return json
}

export async function getInvestmentFormConfig(): Promise<InvestmentFormConfigResponse> {
  const res = await apiFetch('/api/investments/form-config/')
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as InvestmentFormConfigResponse | null
  if (!json) throw new Error('Empty response')
  return json
}

export async function updateInvestmentFormConfig(
  payload: Pick<InvestmentFormConfigResponse, 'uses_companies' | 'allowed_return_types'>,
): Promise<InvestmentFormConfigResponse> {
  const res = await apiFetch('/api/investments/form-config/', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as InvestmentFormConfigResponse | null
  if (!json) throw new Error('Empty response')
  return json
}

export type TelegramWebAppAuthResponse = {
  access: string
  refresh: string
  username: string
}

export type TelegramLoginWidgetConfigResponse = {
  bot_username: string
}

export type TelegramLoginWidgetAuthData = {
  id: string
  first_name?: string
  last_name?: string
  username?: string
  photo_url?: string
  auth_date: string
  hash: string
}

export type TelegramOidcConfigResponse = {
  client_id: string
  redirect_uri: string
  authorization_endpoint: string
  scope: string
}

export type TelegramOidcExchangePayload = {
  code: string
  code_verifier: string
  redirect_uri: string
  nonce?: string
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

export async function getTelegramLoginWidgetConfig(): Promise<TelegramLoginWidgetConfigResponse> {
  const res = await fetch('/api/auth/telegram/login-widget/', {
    method: 'GET',
    headers: { Accept: 'application/json' },
  })
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as TelegramLoginWidgetConfigResponse | null
  return { bot_username: json?.bot_username || '' }
}

export async function exchangeTelegramLoginWidget(
  authData: TelegramLoginWidgetAuthData,
): Promise<TelegramWebAppAuthResponse> {
  const res = await fetch('/api/auth/telegram/login-widget/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify({ auth_data: authData }),
  })
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as TelegramWebAppAuthResponse | null
  if (!json?.access || !json?.refresh || !json?.username) throw new Error('Empty auth response')
  return json
}

export async function getTelegramOidcConfig(): Promise<TelegramOidcConfigResponse> {
  const res = await fetch('/api/auth/telegram/oidc/config/', {
    method: 'GET',
    headers: { Accept: 'application/json' },
  })
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as TelegramOidcConfigResponse | null
  if (!json?.client_id || !json?.redirect_uri || !json?.authorization_endpoint) throw new Error('OIDC not configured')
  return json
}

export async function exchangeTelegramOidc(
  payload: TelegramOidcExchangePayload,
): Promise<TelegramWebAppAuthResponse> {
  const res = await fetch('/api/auth/telegram/oidc/exchange/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as TelegramWebAppAuthResponse | null
  if (!json?.access || !json?.refresh || !json?.username) throw new Error('Empty auth response')
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
  wallet_is_visible_in_cash_section?: boolean
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
  is_visible_in_cash_section: boolean
  cash_register_id: number | null
  bank_account_id: number | null
  corporate_card_account_id: number | null
}

export async function patchWallet(
  id: number,
  payload: {
    opening_balance?: string
    opening_balance_at?: string | null
    is_visible_in_cash_section?: boolean
  },
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
  contracts_required?: boolean
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
  contract_ref_id?: number | null
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
    contract_ref_id?: number | null
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
    contracts_required?: boolean
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

export async function createAutoRequestCopy(templateId: number): Promise<{ request_id: number }> {
  const res = await apiFetch('/api/requests/auto-config/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ template_id: templateId }),
  })
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as { request_id?: number } | null
  if (!json?.request_id) throw new Error('Empty response')
  return { request_id: Number(json.request_id) }
}

export type RequestApprovalConfigStepItem = {
  step: number
  step_type: string
  is_enabled: boolean
  approver_user_ids: number[]
  payment_action_mode?: 'callback' | 'webapp' | 'create'
  payment_webapp_url?: string
  payment_chat_id?: number | null
}

export type RequestApprovalPurposeExceptionItem = {
  id?: number
  name?: string
  is_enabled: boolean
  payment_purpose_ids: number[]
  steps: RequestApprovalConfigStepItem[]
}

export type RequestApprovalConfigPaymentTypeItem = {
  payment_type: string
  is_enabled: boolean
  payment_action_mode_options?: Array<'callback' | 'webapp' | 'create' | string>
  request_not_required_field_options?: string[]
  request_not_required_rules?: Array<{ field: string; operator?: 'eq' | string; value: string }>
  purpose_candidates?: Array<{ id: number; name: string }>
  purpose_exceptions?: RequestApprovalPurposeExceptionItem[]
  steps: RequestApprovalConfigStepItem[]
}

export type RequestApprovalConfigResponse = {
  is_tenant_admin?: boolean
  payment_types: RequestApprovalConfigPaymentTypeItem[]
  approver_candidates: Array<{ id: number; username: string }>
}

export type RequestApprovalConfigUpdatePayload = {
  payment_types: Array<{
    payment_type: string
    is_enabled: boolean
    request_not_required_rules?: Array<{ field: string; operator?: 'eq' | string; value: string }>
    purpose_exceptions?: Array<{
      id?: number
      name?: string
      is_enabled?: boolean
      payment_purpose_ids: number[]
      steps: Array<{
        step: number
        step_type: string
        is_enabled: boolean
        approver_user_ids: number[]
        payment_action_mode?: 'callback' | 'webapp' | 'create'
        payment_webapp_url?: string
        payment_chat_id?: number | null
      }>
    }>
    steps: Array<{
      step: number
      step_type: string
      is_enabled: boolean
      approver_user_ids: number[]
      payment_action_mode?: 'callback' | 'webapp' | 'create'
      payment_webapp_url?: string
      payment_chat_id?: number | null
    }>
  }>
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
  contracts_required?: boolean
  payment_purposes: Array<{ name: string; category: string }>
  defaults?: RequestFormOptionsFormDefaults
}

export type RequestFormOptionsResponse = {
  is_tenant_admin?: boolean
  is_tenant_director?: boolean
  contracts_module_effective?: boolean
  requester_candidates?: RequestFormOptionsRequester[]
  payment_types: RequestFormOptionsPaymentType[]
}

export async function getRequestFormOptions(): Promise<RequestFormOptionsResponse> {
  const res = await apiFetch('/api/requests/form-options/')
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as RequestFormOptionsResponse | null
  if (!json) {
    return { is_tenant_admin: false, is_tenant_director: false, requester_candidates: [], payment_types: [] }
  }
  return {
    is_tenant_admin: json.is_tenant_admin ?? false,
    is_tenant_director: json.is_tenant_director ?? false,
    contracts_module_effective: json.contracts_module_effective ?? false,
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
  contract_ref?: number | null
  amortization_months?: number
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

export async function copyPortalRequest(requestId: number): Promise<{ request_id: number }> {
  const res = await apiFetch(`/api/requests/${requestId}/copy/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({}),
  })
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as { request_id?: number } | null
  if (!json?.request_id) throw new Error('Empty response')
  return { request_id: Number(json.request_id) }
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

// ─── Contracts module ─────────────────────────────────────────────────────────

export type ContractRow = {
  id: number
  tenant: number
  vendor: number
  contract_number: string
  date_from: string
  date_to: string | null
  contract_amount: string
  currency: string
  contract_status: string
  contract_terms: string
  contract_file: string | null
  acc_number: string
  display_status: string
  is_expired: boolean
  created_at: string
  created_by: number | null
  updated_at: string
}

export async function listContracts(params: { vendor?: number }): Promise<ContractRow[]> {
  const sp = new URLSearchParams()
  if (params.vendor != null) sp.set('vendor', String(params.vendor))
  const q = sp.toString()
  const res = await apiFetch(`/api/contracts/${q ? `?${q}` : ''}`)
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = await res.json().catch(() => null)
  return normalizeListPayload<ContractRow>(json)
}

export type ContractCreateMultipartFields = {
  vendor: number
  contract_number: string
  date_from: string
  date_to?: string | null
  contract_amount: string
  currency?: string
  contract_status?: string
  contract_terms?: string
  acc_number?: string
  contract_file?: File | null
}

function appendContractFormData(fd: FormData, fields: ContractCreateMultipartFields) {
  fd.append('vendor', String(fields.vendor))
  fd.append('contract_number', fields.contract_number)
  fd.append('date_from', fields.date_from)
  if (fields.date_to != null && fields.date_to !== '') fd.append('date_to', fields.date_to)
  fd.append('contract_amount', fields.contract_amount)
  fd.append('currency', fields.currency ?? 'UZS')
  fd.append('contract_status', fields.contract_status ?? 'accepted')
  fd.append('contract_terms', fields.contract_terms ?? '')
  fd.append('acc_number', fields.acc_number ?? '')
  if (fields.contract_file) fd.append('contract_file', fields.contract_file)
}

export async function createContract(fields: ContractCreateMultipartFields): Promise<ContractRow> {
  const fd = new FormData()
  appendContractFormData(fd, fields)
  const res = await apiFetch('/api/contracts/', { method: 'POST', body: fd })
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as ContractRow | null
  if (!json) throw new Error('Empty response')
  return json
}

export async function patchContractJson(id: number, body: Record<string, unknown>): Promise<ContractRow> {
  const res = await apiFetch(`/api/contracts/${id}/`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as ContractRow | null
  if (!json) throw new Error('Empty response')
  return json
}

export async function updateContract(id: number, fields: Partial<ContractCreateMultipartFields>): Promise<ContractRow> {
  const fd = new FormData()
  if (fields.vendor != null) fd.append('vendor', String(fields.vendor))
  if (fields.contract_number != null) fd.append('contract_number', fields.contract_number)
  if (fields.date_from != null) fd.append('date_from', fields.date_from)
  if (fields.date_to !== undefined) {
    if (fields.date_to === '' || fields.date_to == null) fd.append('date_to', '')
    else fd.append('date_to', fields.date_to)
  }
  if (fields.contract_amount != null) fd.append('contract_amount', fields.contract_amount)
  if (fields.currency != null) fd.append('currency', fields.currency)
  if (fields.contract_status != null) fd.append('contract_status', fields.contract_status)
  if (fields.contract_terms != null) fd.append('contract_terms', fields.contract_terms)
  if (fields.acc_number != null) fd.append('acc_number', fields.acc_number)
  if (fields.contract_file) fd.append('contract_file', fields.contract_file)
  const res = await apiFetch(`/api/contracts/${id}/`, { method: 'PATCH', body: fd })
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as ContractRow | null
  if (!json) throw new Error('Empty response')
  return json
}

export async function deleteContract(id: number): Promise<void> {
  const res = await apiFetch(`/api/contracts/${id}/`, { method: 'DELETE' })
  if (!res.ok) throw new Error(await parseErrorBody(res))
}

export function contractFileDownloadUrl(contractId: number): string {
  return `/api/contracts/${contractId}/file/`
}

export async function fetchContractFile(contractId: number): Promise<Blob> {
  const res = await apiFetch(contractFileDownloadUrl(contractId), {}, { omitAcceptJson: true })
  if (!res.ok) throw new Error(await parseErrorBody(res))
  return res.blob()
}

// ─── Budgets module ───────────────────────────────────────────────────────────

export type BudgetPeriodType = 'monthly' | 'quarterly' | 'yearly'

export type Budget = {
  id: number
  tenant: number
  name: string
  category: number
  category_name: string
  period_type: BudgetPeriodType
  limit_amount: string
  currency: string
  is_active: boolean
  created_at: string
  created_by: number | null
  spent_amount: string
  remaining_amount: string
  utilization_pct: number
}

export type BudgetCategory = { id: number; name: string }

export type BudgetCreatePayload = {
  name: string
  category: number
  period_type: BudgetPeriodType
  limit_amount: string
  currency: string
  is_active?: boolean
}

export type BudgetUpdatePayload = Partial<BudgetCreatePayload>

export type BudgetSpendDetailItem = {
  id: number
  title: string
  amount: string
  currency: string
  category: string
  status: string
  billing_date: string
  payment_type: string
}

export type BudgetListParams = {
  category?: string
  is_active?: boolean
  year?: number
  period?: number
}

export async function getBudgetCategories(): Promise<BudgetCategory[]> {
  const res = await apiFetch('/api/budgets/categories/')
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = await res.json().catch(() => null)
  return Array.isArray(json) ? (json as BudgetCategory[]) : []
}

export async function getBudgets(params?: BudgetListParams): Promise<Budget[]> {
  const q = new URLSearchParams()
  if (params?.category) q.set('category', params.category)
  if (params?.is_active !== undefined) q.set('is_active', String(params.is_active))
  if (params?.year) q.set('year', String(params.year))
  if (params?.period) q.set('period', String(params.period))
  const query = q.toString()
  const res = await apiFetch(`/api/budgets/${query ? `?${query}` : ''}`)
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = await res.json().catch(() => null)
  return normalizeListPayload<Budget>(json)
}

export async function createBudget(payload: BudgetCreatePayload): Promise<Budget> {
  const res = await apiFetch('/api/budgets/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as Budget | null
  if (!json) throw new Error('Empty response')
  return json
}

export async function updateBudget(id: number, payload: BudgetUpdatePayload): Promise<Budget> {
  const res = await apiFetch(`/api/budgets/${id}/`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as Budget | null
  if (!json) throw new Error('Empty response')
  return json
}

export async function deleteBudget(id: number): Promise<void> {
  const res = await apiFetch(`/api/budgets/${id}/`, { method: 'DELETE' })
  if (!res.ok) throw new Error(await parseErrorBody(res))
}

export async function getBudgetSpendDetail(
  id: number,
  params?: { year?: number; period?: number },
): Promise<BudgetSpendDetailItem[]> {
  const q = new URLSearchParams()
  if (params?.year) q.set('year', String(params.year))
  if (params?.period) q.set('period', String(params.period))
  const query = q.toString()
  const res = await apiFetch(`/api/budgets/${id}/spend-detail/${query ? `?${query}` : ''}`)
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as { results?: BudgetSpendDetailItem[] } | null
  return Array.isArray(json?.results) ? json.results : []
}

