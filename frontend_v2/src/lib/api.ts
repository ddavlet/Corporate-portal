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
      const next = { access: newAccess, refresh: tokens.refresh }
      if (readTgTokens()?.refresh === tokens.refresh) setTgTokens(next)
      if (readPortalTokens()?.refresh === tokens.refresh) setTokens(next)
      headers.set('Authorization', `Bearer ${newAccess}`)
      res = await doFetch()
    } else {
      if (readTgTokens()?.refresh === tokens.refresh) setTgTokens(null)
      if (readPortalTokens()?.refresh === tokens.refresh) setTokens(null)
    }
  }

  if ((res.status === 401 || res.status === 403) && tokens?.access) {
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
}>

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
  /** Всегда пользователь `app` (сервер подставляет при сохранении). */
  requester_id?: number
  last_run_month?: string | null
}

export type AutoRequestConfigResponse = {
  templates: AutoRequestTemplateItem[]
  vendor_candidates: RequestFormConfigCandidateVendor[]
  /** Same shape as form-config payment_types: purposes, vendor_ids, default_company_payer per type */
  form_payment_types: RequestFormConfigPaymentTypeItem[]
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
  payment_action_mode?: 'callback' | 'webapp'
  payment_webapp_url?: string
}

export type RequestApprovalConfigPaymentTypeItem = {
  payment_type: string
  is_enabled: boolean
  steps: RequestApprovalConfigStepItem[]
}

export type RequestApprovalConfigResponse = {
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
    steps: Array<{
      step: number
      step_type: string
      is_enabled: boolean
      approver_user_ids: number[]
      payment_action_mode?: 'callback' | 'webapp'
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

