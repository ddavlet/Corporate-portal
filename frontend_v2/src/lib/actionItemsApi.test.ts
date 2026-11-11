import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiFetchMock = vi.fn()

vi.mock('./api', () => {
  class ApiError extends Error {
    status: number
    constructor(status: number, body: unknown) {
      super(String(body))
      this.status = status
    }
  }
  return {
    ApiError,
    apiFetch: (...args: unknown[]) => apiFetchMock(...args),
    parseErrorBody: async () => 'boom',
  }
})

let sharedMode = false
vi.mock('./portalMode', () => ({ isSharedAppMode: () => sharedMode }))

import { actionItemTag, getActionItems, getActionItemsForPortal, getAllActionItems } from './actionItemsApi'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}

describe('actionItemsApi', () => {
  beforeEach(() => {
    apiFetchMock.mockReset()
    sharedMode = false
  })

  it('builds the tag as kind-id', () => {
    expect(actionItemTag({ kind: 'invest_return', id: 7 })).toBe('invest_return-7')
  })

  it('requests the endpoint silently and returns count and items', async () => {
    apiFetchMock.mockResolvedValue(jsonResponse({ count: 1, items: [{ kind: 'request', id: 3 }] }))
    const res = await getActionItems()
    expect(apiFetchMock).toHaveBeenCalledWith('/api/notifications/action-items/', {}, { silent: true })
    expect(res.count).toBe(1)
    expect(res.items).toHaveLength(1)
  })

  it('falls back to items.length when count is missing', async () => {
    apiFetchMock.mockResolvedValue(jsonResponse({ items: [{ kind: 'request', id: 1 }, { kind: 'request', id: 2 }] }))
    expect((await getActionItems()).count).toBe(2)
  })

  it('treats a malformed body as empty', async () => {
    apiFetchMock.mockResolvedValue(new Response('not json', { status: 200 }))
    expect(await getActionItems()).toEqual({ count: 0, items: [] })
  })

  it('throws on an error status', async () => {
    apiFetchMock.mockResolvedValue(jsonResponse({ detail: 'x' }, 403))
    await expect(getActionItems()).rejects.toMatchObject({ status: 403 })
  })

  it('prefixes the tag with the company for items of the all-companies answer', () => {
    expect(actionItemTag({ kind: 'request', id: 7, tenant: { subdomain: 'acme', name: 'Acme' } })).toBe('acme:request-7')
  })

  it('reads all companies from the tenantless endpoint', async () => {
    const item = { kind: 'request', id: 3, tenant: { subdomain: 'acme', name: 'Acme' }, link: '/requests/3?company=acme' }
    apiFetchMock.mockResolvedValue(jsonResponse({ count: 1, items: [item] }))
    const res = await getAllActionItems()
    expect(apiFetchMock).toHaveBeenCalledWith('/api/notifications/action-items/all/', {}, { silent: true })
    expect(res.items[0].tenant).toEqual({ subdomain: 'acme', name: 'Acme' })
  })

  it('picks the endpoint by portal mode', async () => {
    apiFetchMock.mockImplementation(async () => jsonResponse({ count: 0, items: [] }))
    await getActionItemsForPortal()
    expect(apiFetchMock).toHaveBeenLastCalledWith('/api/notifications/action-items/', {}, { silent: true })
    sharedMode = true
    await getActionItemsForPortal()
    expect(apiFetchMock).toHaveBeenLastCalledWith('/api/notifications/action-items/all/', {}, { silent: true })
  })
})
