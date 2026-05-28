import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { notifyApiErrorMock, notifyNetworkErrorMock } = vi.hoisted(() => ({
  notifyApiErrorMock: vi.fn(),
  notifyNetworkErrorMock: vi.fn(),
}))

vi.mock('./apiNotify', () => ({
  notifyApiError: notifyApiErrorMock,
  notifyNetworkError: notifyNetworkErrorMock,
  notifyApiSuccess: vi.fn(),
}))

import {
  ApiError,
  apiFetch,
  askAiQuestion,
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
  readTgTokens,
  setTgTokens,
  setUnauthorizedHandler,
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

  it('validates AI question and accepts typo key "reponse"', async () => {
    fetchMock.mockResolvedValueOnce(
      createJsonResponse(200, {
        session_id: 'sid-1',
        reponse: 'hello from ai',
      }),
    )

    const response = await askAiQuestion({ question: '  hello?  ' })
    expect(response.session_id).toBe('sid-1')
    expect(response.response).toBe('hello from ai')
  })

  it('rejects empty AI question before network call', async () => {
    await expect(askAiQuestion({ question: '   ' })).rejects.toThrow('Вопрос не может быть пустым')
    expect(fetchMock).not.toHaveBeenCalled()
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
})
