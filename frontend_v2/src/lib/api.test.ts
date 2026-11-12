import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { notifyApiErrorMock, notifyNetworkErrorMock } = vi.hoisted(() => ({
  notifyApiErrorMock: vi.fn(),
  notifyNetworkErrorMock: vi.fn(),
}))

const portalModeState = vi.hoisted(() => ({ shared: false }))

vi.mock('./portalMode', () => ({ isSharedAppMode: () => portalModeState.shared }))

vi.mock('./apiNotify', () => ({
  notifyApiError: notifyApiErrorMock,
  notifyNetworkError: notifyNetworkErrorMock,
  notifyApiSuccess: vi.fn(),
}))

import {
  ApiError,
  apiFetch,
  changePassword,
  confirmPaymentViaWebApp,
  createVendor,
  fetchCursorListPage,
  getCashBalances,
  getModuleCatalog,
  getMyApprovals,
  getRequestFormOptions,
  getSettingsAccess,
  listVendors,
  listVendorsPage,
  parseErrorBody,
  readTgTokens,
  setTenantAccessLostHandler,
  setTgTokens,
  setUnauthorizedHandler,
  submitRequestForApproval,
  validateRequestAttachment,
} from './api'
import { createJsonResponse, createStorageMock, setWindowLocation } from '../test/helpers'

describe('api module', () => {
  const localStorageMock = createStorageMock()
  const sessionStorageMock = createStorageMock()
  const fetchMock = vi.fn()

  beforeEach(() => {
    setWindowLocation('/')
    Object.defineProperty(globalThis, 'localStorage', { value: localStorageMock, configurable: true })
    Object.defineProperty(globalThis, 'sessionStorage', { value: sessionStorageMock, configurable: true })
    Object.defineProperty(globalThis, 'fetch', { value: fetchMock, configurable: true })
    localStorageMock.clear()
    sessionStorageMock.clear()
    fetchMock.mockReset()
    notifyApiErrorMock.mockReset()
    notifyNetworkErrorMock.mockReset()
    setUnauthorizedHandler(null)
  })

  afterEach(() => {
    setUnauthorizedHandler(null)
  })

  it('does not report a cancelled request as a network error', async () => {
    fetchMock.mockRejectedValueOnce(Object.assign(new Error('The operation was aborted.'), { name: 'AbortError' }))
    await expect(apiFetch('/api/reports/statement/')).rejects.toMatchObject({ name: 'AbortError' })
    expect(notifyNetworkErrorMock).not.toHaveBeenCalled()
  })

  it('shows toast on failed GET', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse(500, { detail: 'Сервер недоступен' }))

    const res = await apiFetch('/api/example')

    expect(res.status).toBe(500)
    expect(notifyApiErrorMock).toHaveBeenCalledWith('Сервер недоступен')
  })

  it('does not toast on failed POST by default (caller handles mutation errors)', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse(400, { detail: 'Неверные данные' }))

    const res = await apiFetch('/api/example', { method: 'POST' })

    expect(res.status).toBe(400)
    expect(notifyApiErrorMock).not.toHaveBeenCalled()
  })

  it('shows toast on failed PATCH when notifyOnError is set', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse(400, { detail: 'Нельзя изменить статус' }))

    const res = await apiFetch('/api/requests/1/', { method: 'PATCH' }, { notifyOnError: true })

    expect(res.status).toBe(400)
    expect(notifyApiErrorMock).toHaveBeenCalledWith('Нельзя изменить статус')
  })

  it('respects silent option for GET errors', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse(404, { detail: 'Не найдено' }))

    await apiFetch('/api/example', {}, { silent: true })

    expect(notifyApiErrorMock).not.toHaveBeenCalled()
  })

  it('does not toast on optional balances 403', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse(403, { detail: 'forbidden' }))

    const balances = await getCashBalances()

    expect(balances).toEqual([])
    expect(notifyApiErrorMock).not.toHaveBeenCalled()
  })

  it('shows network toast when fetch throws', async () => {
    fetchMock.mockRejectedValueOnce(new TypeError('Failed to fetch'))

    await expect(apiFetch('/api/example')).rejects.toThrow('Failed to fetch')
    expect(notifyNetworkErrorMock).toHaveBeenCalledTimes(1)
  })

  it('stores and reads telegram tokens', () => {
    setTgTokens({ access: 'a1', refresh: 'r1' })
    expect(readTgTokens()).toEqual({ access: 'a1', refresh: 'r1' })

    setTgTokens(null)
    expect(readTgTokens()).toBeNull()
  })

  it('uses portal token in non-tg path', async () => {
    localStorageMock.setItem(
      'kolberg_v2_tokens',
      JSON.stringify({ access: 'portal-access', refresh: 'portal-refresh', username: 'u1' }),
    )
    sessionStorageMock.setItem('kolberg_v2_tg_tokens', JSON.stringify({ access: 'tg-access', refresh: 'tg-refresh' }))
    fetchMock.mockResolvedValueOnce(createJsonResponse(200, { ok: true }))

    await apiFetch('/api/example')

    const call = fetchMock.mock.calls[0]
    const options = call[1] as RequestInit
    const headers = options.headers as Headers
    expect(headers.get('Authorization')).toBe('Bearer portal-access')
  })

  it('prefers tg token in tg path', async () => {
    setWindowLocation('/tg/payments')
    localStorageMock.setItem('kolberg_v2_tokens', JSON.stringify({ access: 'portal-access', refresh: 'portal-refresh' }))
    sessionStorageMock.setItem('kolberg_v2_tg_tokens', JSON.stringify({ access: 'tg-access', refresh: 'tg-refresh' }))
    fetchMock.mockResolvedValueOnce(createJsonResponse(200, { ok: true }))

    await apiFetch('/api/example')

    const call = fetchMock.mock.calls[0]
    const options = call[1] as RequestInit
    const headers = options.headers as Headers
    expect(headers.get('Authorization')).toBe('Bearer tg-access')
  })

  it('refreshes access token on 401 and retries request', async () => {
    localStorageMock.setItem('kolberg_v2_tokens', JSON.stringify({ access: 'old-a', refresh: 'old-r', username: 'john' }))
    fetchMock
      .mockResolvedValueOnce(createJsonResponse(401, { detail: 'expired' }))
      .mockResolvedValueOnce(createJsonResponse(200, { access: 'new-a' }))
      .mockResolvedValueOnce(createJsonResponse(200, { ok: true }))

    const res = await apiFetch('/api/secure')
    expect(res.status).toBe(200)
    expect(fetchMock).toHaveBeenCalledTimes(3)
    const saved = JSON.parse(localStorageMock.getItem('kolberg_v2_tokens') as string) as {
      access: string
      refresh: string
      username: string
    }
    expect(saved.access).toBe('new-a')
    expect(saved.refresh).toBe('old-r')
    expect(saved.username).toBe('john')
  })

  it('clears tokens and calls unauthorized handler on 401', async () => {
    const onUnauthorized = vi.fn()
    setUnauthorizedHandler(onUnauthorized)
    localStorageMock.setItem('kolberg_v2_tokens', JSON.stringify({ access: 'bad-a', refresh: 'bad-r' }))
    fetchMock.mockResolvedValueOnce(createJsonResponse(401, { detail: 'bad' })).mockResolvedValueOnce(createJsonResponse(401, {}))

    await apiFetch('/api/secure')

    expect(onUnauthorized).toHaveBeenCalledTimes(1)
    expect(localStorageMock.getItem('kolberg_v2_tokens')).toBeNull()
  })

  it('does not call global unauthorized handler when disabled by option', async () => {
    const onUnauthorized = vi.fn()
    setUnauthorizedHandler(onUnauthorized)
    localStorageMock.setItem('kolberg_v2_tokens', JSON.stringify({ access: 'bad-a', refresh: 'bad-r' }))
    fetchMock.mockResolvedValueOnce(createJsonResponse(401, { detail: 'bad' })).mockResolvedValueOnce(createJsonResponse(401, {}))

    await apiFetch('/api/optional', {}, { treatAuthErrorsAsGlobal: false })

    expect(onUnauthorized).not.toHaveBeenCalled()
  })

  it('normalizes settings-access response', async () => {
    fetchMock.mockResolvedValueOnce(
      createJsonResponse(200, {
        tenant_name: 'Tenant 1',
        can_open_settings: 1,
        can_open_admin: 0,
        can_manage_tenant_settings: true,
        can_manage_requests_settings: null,
        can_manage_wallet_settings: 'yes',
        roles: ['director'],
      }),
    )

    const response = await getSettingsAccess()
    expect(response).toEqual({
      tenant_name: 'Tenant 1',
      can_open_settings: true,
      can_open_admin: false,
      can_manage_tenant_settings: true,
      can_manage_requests_settings: false,
      can_manage_wallet_settings: true,
      roles: ['director'],
    })
  })

  it('returns defaults for empty request-form-options payload', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse(200, null))

    const response = await getRequestFormOptions()
    expect(response).toEqual({ is_tenant_admin: false, is_tenant_director: false, requester_candidates: [], payment_types: [] })
  })

  it('returns backend detail for failed password change', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse(400, { detail: 'Старый пароль неверный' }))

    await expect(changePassword({ old_password: 'bad', new_password: 'new1' })).rejects.toThrow('Старый пароль неверный')
  })

  it('validates request attachment extension and size', () => {
    const badType = { name: 'archive.zip', size: 100 } as File
    const bigPdf = { name: 'x.pdf', size: 11 * 1024 * 1024 } as File
    const okPng = { name: 'image.PNG', size: 1024 } as File

    expect(validateRequestAttachment(badType)).toContain('Недопустимый тип файла')
    expect(validateRequestAttachment(bigPdf)).toBe('Файл превышает 10 МБ.')
    expect(validateRequestAttachment(okPng)).toBeNull()
  })

  it('returns module catalog array from wrapped payload', async () => {
    fetchMock.mockResolvedValueOnce(
      createJsonResponse(200, {
        modules: [{ module_key: 'cash', display_name: 'Касса', tenant_enabled: true, user_allowed: true, effective_enabled: true }],
      }),
    )
    const modules = await getModuleCatalog()
    expect(modules).toHaveLength(1)
    expect(modules[0].module_key).toBe('cash')
  })

  it('returns empty array for my approvals when payload is not array', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse(200, { items: [] }))
    const approvals = await getMyApprovals()
    expect(approvals).toEqual([])
  })

  it('returns [] for cash balances on 403', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse(403, { detail: 'forbidden' }))
    const balances = await getCashBalances()
    expect(balances).toEqual([])
  })

  it('builds vendors query params and parses results', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse(200, { results: [{ id: 1, kind: 'cash', name: 'Test', tenant: 1, created_at: '', created_by: 1 }] }))
    const rows = await listVendors({ kind: 'cash', search: '  abc  ' })
    expect(rows).toHaveLength(1)
    const [input] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(input).toContain('/api/vendors/?kind=cash&search=abc')
  })

  it('loads one page of vendors with page_size and does not follow the cursor', async () => {
    fetchMock.mockResolvedValueOnce(
      createJsonResponse(200, {
        results: [{ id: 1, kind: 'transfer', name: 'Test', tenant: 1, created_at: '', created_by: 1 }],
        next: 'https://x.kolberg.uz/api/vendors/?cursor=abc&page_size=200',
        previous: null,
      }),
    )
    const rows = await listVendorsPage({ kind: 'transfer', search: ' ром ', page_size: 200 })
    expect(rows).toHaveLength(1)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [input] = fetchMock.mock.calls[0] as [string, RequestInit]
    const url = new URL(input, 'http://localhost')
    expect(url.pathname).toBe('/api/vendors/')
    expect(url.searchParams.get('kind')).toBe('transfer')
    expect(url.searchParams.get('search')).toBe('ром')
    expect(url.searchParams.get('page_size')).toBe('200')
  })

  it('sends createVendor payload and returns row', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse(200, { id: 7, kind: 'transfer', name: 'OOO Test', tenant: 1, created_at: '', created_by: 1 }))
    const row = await createVendor({ kind: 'transfer', name: 'OOO Test', inn: '123', account_number: '408' })
    expect(row.id).toBe(7)
    const [, options] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(options.method).toBe('POST')
    expect(options.body).toBe(JSON.stringify({ kind: 'transfer', name: 'OOO Test', inn: '123', account_number: '408' }))
  })

  it('throws ApiError with status 403 when createVendor is forbidden', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse(403, { detail: 'You do not have permission to perform this action.' }))
    const err = await createVendor({ kind: 'cash', name: 'OOO Test' }).catch((e) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect((err as ApiError).status).toBe(403)
    expect((err as ApiError).message).toBe('You do not have permission to perform this action.')
  })

  it('returns request payload from confirmPaymentViaWebApp', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse(200, { request: { id: 11, status: 'approved' } }))
    const result = await confirmPaymentViaWebApp({ approval_id: 44, expense_id: 'INV-1' })
    expect(result.request).toEqual({ id: 11, status: 'approved' })
  })

  it('submitRequestForApproval posts to submit-for-approval and returns new status', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse(200, { id: 6323, status: '1' }))
    const result = await submitRequestForApproval(6323)
    expect(result).toEqual({ status: '1' })
    const [input, options] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(input).toContain('/api/requests/6323/submit-for-approval/')
    expect(options.method).toBe('POST')
  })

  it('submitRequestForApproval surfaces conflict detail when already submitted', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse(409, { detail: 'Request already submitted for approval.' }))
    await expect(submitRequestForApproval(7)).rejects.toThrow('Request already submitted for approval.')
  })

  it('fetchCursorListPage parses cursor envelope and legacy array', async () => {
    fetchMock.mockResolvedValueOnce(
      createJsonResponse(200, { results: [{ id: 1 }], next: 'https://host/api/items/?cursor=x', previous: null }),
    )
    const page = await fetchCursorListPage<{ id: number }>('/api/items/')
    expect(page.results).toEqual([{ id: 1 }])
    expect(page.next).toContain('cursor=x')

    fetchMock.mockResolvedValueOnce(createJsonResponse(200, [{ id: 2 }]))
    const legacy = await fetchCursorListPage<{ id: number }>('/api/items/')
    expect(legacy.results).toEqual([{ id: 2 }])
    expect(legacy.next).toBeNull()
  })

  it('reads DRF field errors instead of a generic server error', async () => {
    expect(await parseErrorBody(createJsonResponse(400, { month: ['Месяц ещё не наступил.'] }))).toBe('Месяц ещё не наступил.')
    expect(
      await parseErrorBody(createJsonResponse(400, { year: ['Укажите год.'], non_field_errors: ['Неверный период.'] })),
    ).toBe('Укажите год. Неверный период.')
    expect(await parseErrorBody(createJsonResponse(400, { detail: 'Нет доступа.' }))).toBe('Нет доступа.')
    expect(await parseErrorBody(createJsonResponse(500, null))).toBe('Ошибка сервера (500)')
  })
})

describe('apiFetch X-Tenant on the shared app host', () => {
  const localStorageMock = createStorageMock()
  const sessionStorageMock = createStorageMock()
  const fetchMock = vi.fn()

  function sentHeaders(call = 0): Headers {
    return (fetchMock.mock.calls[call][1] as RequestInit).headers as Headers
  }

  beforeEach(() => {
    setWindowLocation('/app/requests')
    Object.defineProperty(globalThis, 'localStorage', { value: localStorageMock, configurable: true })
    Object.defineProperty(globalThis, 'sessionStorage', { value: sessionStorageMock, configurable: true })
    Object.defineProperty(globalThis, 'fetch', { value: fetchMock, configurable: true })
    localStorageMock.clear()
    sessionStorageMock.clear()
    fetchMock.mockReset()
    fetchMock.mockImplementation(async () => createJsonResponse(200, {}))
    localStorageMock.setItem('kolberg_v2_tokens', JSON.stringify({ access: 'acc', refresh: 'ref', username: 'ivan' }))
    sessionStorageMock.setItem('kolberg_v2_company', 'acme')
    portalModeState.shared = true
    notifyApiErrorMock.mockReset()
    setTenantAccessLostHandler(null)
  })

  afterEach(() => {
    portalModeState.shared = false
    setTenantAccessLostHandler(null)
  })

  it('sends the tab company with the token', async () => {
    await apiFetch('/api/requests/')
    expect(sentHeaders().get('X-Tenant')).toBe('acme')
    expect(sentHeaders().get('Authorization')).toBe('Bearer acc')
  })

  it('sends it for an absolute URL of the same origin (file links from the server)', async () => {
    await apiFetch('https://example.com/api/files/download/?path=x')
    expect(sentHeaders().get('X-Tenant')).toBe('acme')
  })

  it('never sends it to another origin', async () => {
    await apiFetch('https://files.example.org/api/files/download/?path=x')
    expect(sentHeaders().has('X-Tenant')).toBe(false)
  })

  it('does not send it on a tenant subdomain', async () => {
    portalModeState.shared = false
    await apiFetch('/api/requests/')
    expect(sentHeaders().has('X-Tenant')).toBe(false)
  })

  it('does not send it to same-origin URLs outside /api/', async () => {
    await apiFetch('/static/app.js')
    expect(sentHeaders().has('X-Tenant')).toBe(false)
  })

  it('does not send it in the Telegram Mini App', async () => {
    setWindowLocation('/app/tg/requests')
    await apiFetch('/api/requests/')
    expect(sentHeaders().has('X-Tenant')).toBe(false)
  })

  it('does not send it before a company is picked', async () => {
    sessionStorageMock.clear()
    await apiFetch('/api/me/companies/')
    expect(sentHeaders().has('X-Tenant')).toBe(false)
  })

  it('hands a lost company (403 tenant_forbidden) to the handler instead of a toast', async () => {
    const onLost = vi.fn(() => true)
    setTenantAccessLostHandler(onLost)
    fetchMock.mockResolvedValueOnce(createJsonResponse(403, { detail: 'Нет доступа к компании.', code: 'tenant_forbidden' }))

    const res = await apiFetch('/api/requests/')

    expect(res.status).toBe(403)
    expect(onLost).toHaveBeenCalledWith('tenant_forbidden', 'acme')
    expect(notifyApiErrorMock).not.toHaveBeenCalled()
  })

  it('reports tenant_required with no company sent', async () => {
    const onLost = vi.fn(() => true)
    setTenantAccessLostHandler(onLost)
    sessionStorageMock.clear()
    fetchMock.mockResolvedValueOnce(createJsonResponse(403, { detail: 'Не выбрана компания.', code: 'tenant_required' }))

    await apiFetch('/api/requests/')

    expect(onLost).toHaveBeenCalledWith('tenant_required', null)
  })

  it('keeps the toast when the handler declines, and for other 403 answers', async () => {
    const onLost = vi.fn(() => false)
    setTenantAccessLostHandler(onLost)
    fetchMock
      .mockResolvedValueOnce(createJsonResponse(403, { detail: 'Нет доступа к компании.', code: 'tenant_forbidden' }))
      .mockResolvedValueOnce(createJsonResponse(403, { detail: 'Недостаточно прав.' }))

    await apiFetch('/api/requests/')
    await apiFetch('/api/requests/')

    expect(onLost).toHaveBeenCalledTimes(1)
    expect(notifyApiErrorMock).toHaveBeenCalledTimes(2)
  })

  it('does not call the handler on a tenant subdomain', async () => {
    portalModeState.shared = false
    const onLost = vi.fn(() => true)
    setTenantAccessLostHandler(onLost)
    fetchMock.mockResolvedValueOnce(createJsonResponse(403, { detail: 'x', code: 'tenant_forbidden' }))

    await apiFetch('/api/requests/')

    expect(onLost).not.toHaveBeenCalled()
    expect(notifyApiErrorMock).toHaveBeenCalledTimes(1)
  })

  it('sends each tab its own company (two tabs, one device)', async () => {
    const otherTab = createStorageMock()
    otherTab.setItem('kolberg_v2_company', 'beta')

    await apiFetch('/api/requests/')
    Object.defineProperty(globalThis, 'sessionStorage', { value: otherTab, configurable: true })
    await apiFetch('/api/requests/')

    expect(sentHeaders(0).get('X-Tenant')).toBe('acme')
    expect(sentHeaders(1).get('X-Tenant')).toBe('beta')
  })
})
