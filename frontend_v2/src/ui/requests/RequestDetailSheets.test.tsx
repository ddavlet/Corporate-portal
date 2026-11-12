import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { message } from 'antd'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { contrastRatio } from '../../test/contrast'
import { resetViewport, setViewport } from '../../test/viewport'
import type { ApprovalItem, RequestDetail } from './RequestDetailModal'
import { RequestDetailPage } from './RequestDetailPage'

// The real API helpers run against a stubbed fetch: the tests check the request bodies that reach the server.

const refreshActionItems = vi.hoisted(() => vi.fn())
vi.mock('../../lib/useActionItems', () => ({
  refreshActionItems: () => refreshActionItems(),
  useActionItems: () => ({ items: [], count: 0, loading: false, error: false, refresh: refreshActionItems }),
}))

vi.mock('../../lib/portalMode', () => ({ isSharedAppMode: () => false }))

const ME = 7

vi.mock('../auth', () => ({
  useAuth: () => ({ accessToken: `header.${btoa(JSON.stringify({ user_id: 7 })).replace(/=+$/, '')}.signature` }),
}))

const DECISION_URL = '/api/requests/77/approvals/decision/'
const PAYMENT_URL = '/api/requests/approvals/payment-webapp/confirm/'

function makeDetail(myApproval: Partial<ApprovalItem>): RequestDetail {
  return {
    id: 77,
    title: 'Аренда офиса',
    description: '',
    amount: 2500000,
    currency: 'UZS',
    status: '1',
    urgency: 'Обычно',
    payment_type: 'Перечисление',
    category: 'Аренда',
    vendor: 'ООО Альфа',
    requester: 3,
    submitted_at: '2026-11-09T09:05:00Z',
    billing_date: '2026-11-01',
    approvals: [
      {
        id: 21,
        step: 1,
        step_type: 'approval',
        decision: 'pending',
        approver_user: ME,
        approver_username: 'me',
        ...myApproval,
      },
    ],
    comments: [],
  }
}

let detail: RequestDetail
const fetchMock = vi.fn()

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function callsTo(url: string): Array<Record<string, unknown>> {
  return fetchMock.mock.calls
    .filter(([input, init]) => String(input) === url && (init as RequestInit | undefined)?.method === 'POST')
    .map(([, init]) => JSON.parse(String((init as RequestInit).body)) as Record<string, unknown>)
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/requests/77']}>
      <Routes>
        <Route path="/requests/:id" element={<RequestDetailPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  setViewport('phone')
  fetchMock.mockReset()
  fetchMock.mockImplementation(async (input: unknown, init?: RequestInit) => {
    const url = String(input)
    if (url === '/api/requests/77/') return json(detail)
    if (url === DECISION_URL && init?.method === 'POST') return json({ ok: true })
    if (url === PAYMENT_URL && init?.method === 'POST') return json({ request: { id: 77, status: 'PAYED' } })
    return json({})
  })
  vi.stubGlobal('fetch', fetchMock)
  refreshActionItems.mockReset().mockResolvedValue(undefined)
  vi.spyOn(message, 'success').mockImplementation(() => undefined as never)
  vi.spyOn(message, 'error').mockImplementation(() => undefined as never)
})

afterEach(() => {
  resetViewport()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('Reject sheet', () => {
  beforeEach(() => {
    detail = makeDetail({})
  })

  async function openRejectSheet() {
    renderPage()
    const bar = await screen.findByTestId('request-decision-bar')
    fireEvent.click(within(bar).getByRole('button', { name: 'Отклонить' }))
    return screen.findByRole('dialog', { name: 'Отклонить шаг 1' })
  }

  it('shows the request summary and pins «Отмена» and «Отклонить» in the sheet footer', async () => {
    const sheet = await openRejectSheet()
    const summary = within(sheet).getByTestId('reject-request-summary')
    expect(summary).toHaveTextContent('#77 · Аренда офиса')
    expect(summary).toHaveTextContent('ООО Альфа')
    expect(summary).toHaveTextContent('2 500 000 UZS')

    // The actions sit outside the scrolling body, next to the home indicator inset.
    const footer = within(sheet).getByRole('button', { name: 'Отклонить' }).closest('.ant-drawer-footer')
    expect(footer).not.toBeNull()
    expect(within(footer as HTMLElement).getByRole('button', { name: 'Отмена' })).toBeInTheDocument()
    expect(footer).not.toContainElement(within(sheet).getByLabelText(/Причина/))
  })

  it('sends the typed reason as comment', async () => {
    const sheet = await openRejectSheet()
    fireEvent.change(within(sheet).getByLabelText(/Причина/), { target: { value: 'Нет договора' } })
    fireEvent.click(within(sheet).getByRole('button', { name: 'Отклонить' }))

    await waitFor(() => expect(callsTo(DECISION_URL)).toEqual([{ step: 1, decision: 'rejected', comment: 'Нет договора' }]))
    await waitFor(() => expect(refreshActionItems).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Отклонить шаг 1' })).toBeNull())
  })

  it('rejects without comment when no reason was given', async () => {
    const sheet = await openRejectSheet()
    fireEvent.click(within(sheet).getByRole('button', { name: 'Отклонить' }))

    await waitFor(() => expect(callsTo(DECISION_URL)).toEqual([{ step: 1, decision: 'rejected' }]))
  })

  it('closes on «Отмена» without calling the API and starts empty when reopened', async () => {
    const sheet = await openRejectSheet()
    fireEvent.change(within(sheet).getByLabelText(/Причина/), { target: { value: 'Черновик причины' } })
    fireEvent.click(within(sheet).getByRole('button', { name: 'Отмена' }))
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Отклонить шаг 1' })).toBeNull())
    expect(callsTo(DECISION_URL)).toEqual([])

    const bar = screen.getByTestId('request-decision-bar')
    fireEvent.click(within(bar).getByRole('button', { name: 'Отклонить' }))
    const reopened = await screen.findByRole('dialog', { name: 'Отклонить шаг 1' })
    expect(within(reopened).getByLabelText(/Причина/)).toHaveValue('')
  })

  it('leaves comment out when the reason is only spaces', async () => {
    const sheet = await openRejectSheet()
    fireEvent.change(within(sheet).getByLabelText(/Причина/), { target: { value: '   ' } })
    fireEvent.click(within(sheet).getByRole('button', { name: 'Отклонить' }))

    await waitFor(() => expect(callsTo(DECISION_URL)).toEqual([{ step: 1, decision: 'rejected' }]))
  })

  it('keeps the sheet open when the decision fails', async () => {
    fetchMock.mockImplementation(async (input: unknown, init?: RequestInit) => {
      const url = String(input)
      if (url === '/api/requests/77/') return json(detail)
      if (url === DECISION_URL && init?.method === 'POST') return json({ detail: 'Шаг уже обработан' }, 400)
      return json({})
    })
    const sheet = await openRejectSheet()
    fireEvent.click(within(sheet).getByRole('button', { name: 'Отклонить' }))

    await waitFor(() => expect(message.error).toHaveBeenCalledWith('Шаг уже обработан'))
    expect(screen.getByRole('dialog', { name: 'Отклонить шаг 1' })).toBeInTheDocument()
    expect(refreshActionItems).not.toHaveBeenCalled()
  })
})

describe('Payment sheet', () => {
  beforeEach(() => {
    detail = makeDetail({ id: 31, step_type: 'payment', payment_action_mode: 'webapp' })
  })

  async function openPaymentSheet() {
    renderPage()
    const bar = await screen.findByTestId('request-decision-bar')
    fireEvent.click(within(bar).getByRole('button', { name: 'Подтвердить выплату' }))
    return screen.findByRole('dialog', { name: 'Подтверждение выплаты' })
  }

  it('shows the summary and asks for the document number before calling the API', async () => {
    const sheet = await openPaymentSheet()
    const summary = within(sheet).getByTestId('payment-confirm-summary')
    expect(summary).toHaveTextContent('#77 · Аренда офиса')
    expect(summary).toHaveTextContent('ООО Альфа')
    expect(summary).toHaveTextContent('2 500 000 UZS')

    fireEvent.click(within(sheet).getByRole('button', { name: 'Подтвердить' }))

    expect(await within(sheet).findByText('Введите номер платёжного документа')).toBeInTheDocument()
    expect(within(sheet).getByLabelText('Номер платёжного документа')).toHaveAttribute('aria-invalid', 'true')
    expect(callsTo(PAYMENT_URL)).toEqual([])
  })

  it('ties a readable error to the field', async () => {
    const sheet = await openPaymentSheet()
    fireEvent.click(within(sheet).getByRole('button', { name: 'Подтвердить' }))

    const error = await within(sheet).findByRole('alert')
    expect(error).toHaveTextContent('Введите номер платёжного документа')
    expect(within(sheet).getByLabelText('Номер платёжного документа')).toHaveAccessibleDescription(
      'Введите номер платёжного документа',
    )
    expect(error.style.color).not.toBe('')
    expect(contrastRatio(error.style.color)).toBeGreaterThanOrEqual(4.5)

    fireEvent.change(within(sheet).getByLabelText('Номер платёжного документа'), { target: { value: '1' } })
    expect(within(sheet).getByLabelText('Номер платёжного документа')).not.toHaveAttribute('aria-describedby')
  })

  it('pins «Отмена» and «Подтвердить» in the sheet footer', async () => {
    const sheet = await openPaymentSheet()
    const footer = within(sheet).getByRole('button', { name: 'Подтвердить' }).closest('.ant-drawer-footer')
    expect(footer).not.toBeNull()
    expect(within(footer as HTMLElement).getByRole('button', { name: 'Отмена' })).toBeInTheDocument()
  })

  it('confirms the payment with the approval id and the number', async () => {
    const sheet = await openPaymentSheet()
    fireEvent.change(within(sheet).getByLabelText('Номер платёжного документа'), { target: { value: ' 4512 ' } })
    fireEvent.click(within(sheet).getByRole('button', { name: 'Подтвердить' }))

    await waitFor(() => expect(callsTo(PAYMENT_URL)).toEqual([{ approval_id: 31, expense_id: '4512' }]))
    await waitFor(() => expect(refreshActionItems).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Подтверждение выплаты' })).toBeNull())
  })

  it('offers the known expense number and sends it as is', async () => {
    detail = { ...makeDetail({ id: 31, step_type: 'payment', payment_action_mode: 'webapp' }), expense_id: '9001' }
    const sheet = await openPaymentSheet()
    expect(within(sheet).getByLabelText('Номер платёжного документа')).toHaveValue('9001')
    fireEvent.click(within(sheet).getByRole('button', { name: 'Подтвердить' }))

    await waitFor(() => expect(callsTo(PAYMENT_URL)).toEqual([{ approval_id: 31, expense_id: '9001' }]))
  })

  it('drops the old error and typed number when the sheet is reopened', async () => {
    const sheet = await openPaymentSheet()
    fireEvent.click(within(sheet).getByRole('button', { name: 'Подтвердить' }))
    await within(sheet).findByRole('alert')
    fireEvent.change(within(sheet).getByLabelText('Номер платёжного документа'), { target: { value: '55' } })
    fireEvent.click(within(sheet).getByRole('button', { name: 'Отмена' }))
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Подтверждение выплаты' })).toBeNull())
    expect(callsTo(PAYMENT_URL)).toEqual([])

    const bar = screen.getByTestId('request-decision-bar')
    fireEvent.click(within(bar).getByRole('button', { name: 'Подтвердить выплату' }))
    const reopened = await screen.findByRole('dialog', { name: 'Подтверждение выплаты' })
    expect(within(reopened).getByLabelText('Номер платёжного документа')).toHaveValue('')
    expect(within(reopened).queryByRole('alert')).toBeNull()
  })

  it('sends the payment once when Enter is pressed in the field', async () => {
    const sheet = await openPaymentSheet()
    const field = within(sheet).getByLabelText('Номер платёжного документа')
    fireEvent.change(field, { target: { value: '77' } })
    fireEvent.keyDown(field, { key: 'Enter', code: 'Enter', keyCode: 13, charCode: 13 })

    await waitFor(() => expect(callsTo(PAYMENT_URL)).toEqual([{ approval_id: 31, expense_id: '77' }]))
  })
})
