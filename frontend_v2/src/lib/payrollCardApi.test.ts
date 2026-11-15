import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiFetchMock = vi.fn()

vi.mock('./api', () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...args),
  parseErrorBody: async (res: Response) => {
    const json = (await res.json().catch(() => null)) as { detail?: string } | null
    return json?.detail ?? `Ошибка сервера (${res.status})`
  },
}))

import {
  PayrollCardApiError,
  assignCardPayout,
  getPayrollCardAttention,
  linkBankEmployee,
  updateExpectedCard,
} from './payrollCardApi'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}

const EMPTY = { enabled: true, count: 0, unlinked: [], awaiting_document: [], missing_card: [], overpaid: [] }

describe('payrollCardApi', () => {
  beforeEach(() => {
    apiFetchMock.mockReset()
  })

  it('requests attention silently and returns the body', async () => {
    apiFetchMock.mockResolvedValue(jsonResponse(EMPTY))
    await expect(getPayrollCardAttention()).resolves.toEqual(EMPTY)
    expect(apiFetchMock).toHaveBeenCalledWith('/api/payroll/card-payouts/attention/', {}, { silent: true })
  })

  it.each([403, 404])('returns null on %s', async (status) => {
    apiFetchMock.mockResolvedValue(jsonResponse({ detail: 'нет доступа' }, status))
    await expect(getPayrollCardAttention()).resolves.toBeNull()
  })

  it('throws on a server error', async () => {
    apiFetchMock.mockResolvedValue(jsonResponse({ detail: 'сломалось' }, 500))
    await expect(getPayrollCardAttention()).rejects.toBeInstanceOf(PayrollCardApiError)
  })

  it('posts the link body and surfaces the 400 text', async () => {
    apiFetchMock.mockResolvedValue(
      jsonResponse({ detail: 'Этот сотрудник банка уже привязан к «Иванов И.».' }, 400),
    )
    const error = await linkBankEmployee({ bank_employee_id: 5, employee_id: 7 }).catch((e: unknown) => e)
    expect(error).toBeInstanceOf(PayrollCardApiError)
    expect((error as PayrollCardApiError).status).toBe(400)
    expect((error as Error).message).toBe('Этот сотрудник банка уже привязан к «Иванов И.».')
    const [url, init] = apiFetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/api/payroll/bank-employee-links/')
    expect(init.method).toBe('POST')
    expect(JSON.parse(String(init.body))).toEqual({ bank_employee_id: 5, employee_id: 7 })
  })

  it('posts the assign body to the payout url', async () => {
    apiFetchMock.mockResolvedValue(jsonResponse({ payout_id: 11, employee_id: 7, document_id: null }))
    await expect(assignCardPayout(11, 7)).resolves.toEqual({ payout_id: 11, employee_id: 7, document_id: null })
    const [url, init] = apiFetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/api/payroll/card-payouts/11/assign/')
    expect(init.method).toBe('POST')
    expect(JSON.parse(String(init.body))).toEqual({ employee_id: 7 })
  })

  it('puts expected card items', async () => {
    apiFetchMock.mockResolvedValue(jsonResponse({ can_pay: true, employees: [] }))
    await updateExpectedCard(3, [{ employee_id: 7, amount: '2000000.00' }])
    const [url, init] = apiFetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/api/payroll/documents/3/expected-card/')
    expect(init.method).toBe('PUT')
    expect(JSON.parse(String(init.body))).toEqual({ items: [{ employee_id: 7, amount: '2000000.00' }] })
  })
})
