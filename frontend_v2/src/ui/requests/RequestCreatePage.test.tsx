import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import dayjs from 'dayjs'
import timezone from 'dayjs/plugin/timezone'
import utc from 'dayjs/plugin/utc'
import { message } from 'antd'
import { MemoryRouter, Route, Routes, useLocation, useParams } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest'
import type { RequestFormOptionsPaymentType, RequestFormOptionsResponse } from '../../lib/api'
import { RequestCreatePage } from './RequestCreatePage'

dayjs.extend(utc)
dayjs.extend(timezone)

// Characterization of the portal create form BEFORE its logic moves into a hook: what the form shows for a
// form-options answer, what it refuses to submit and what it sends to the API.

const api = vi.hoisted(() => ({
  getRequestFormOptions: vi.fn(),
  listVendors: vi.fn(),
  listContracts: vi.fn(),
  createPortalRequest: vi.fn(),
  uploadRequestAttachment: vi.fn(),
}))

vi.mock('../../lib/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../lib/api')>()),
  getRequestFormOptions: (...a: unknown[]) => api.getRequestFormOptions(...a),
  listVendors: (...a: unknown[]) => api.listVendors(...a),
  listContracts: (...a: unknown[]) => api.listContracts(...a),
  createPortalRequest: (...a: unknown[]) => api.createPortalRequest(...a),
  uploadRequestAttachment: (...a: unknown[]) => api.uploadRequestAttachment(...a),
}))

function paymentType(over: Partial<RequestFormOptionsPaymentType> = {}): RequestFormOptionsPaymentType {
  return {
    payment_type: 'Перечисление',
    requester_ids: [],
    requesters: [],
    vendor_ids: [],
    payment_purposes: [],
    ...over,
  }
}

function formOptions(over: Partial<RequestFormOptionsResponse> = {}): RequestFormOptionsResponse {
  return { payment_types: [paymentType()], ...over }
}

const vendorRows = [
  { id: 1, tenant: 1, kind: 'transfer', name: 'ООО Ромашка', inn: '123456789', created_at: '', created_by: 1 },
  { id: 2, tenant: 1, kind: 'transfer', name: 'ООО Лютик', inn: null, created_at: '', created_by: 1 },
]

function DetailProbe() {
  const { id } = useParams()
  const state = useLocation().state
  return <div data-testid="detail">{`id=${id} state=${JSON.stringify(state)}`}</div>
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/requests/new']}>
      <Routes>
        <Route path="/requests/new" element={<RequestCreatePage />} />
        <Route path="/requests/:id" element={<DetailProbe />} />
      </Routes>
    </MemoryRouter>,
  )
}

async function pickOption(placeholder: string, label: string) {
  fireEvent.mouseDown(await screen.findByText(placeholder))
  const option = await waitFor(() => {
    const el = Array.from(document.querySelectorAll('.ant-select-item-option')).find(
      (e) => (e.textContent ?? '').trim() === label,
    )
    if (!el) throw new Error(`option ${label} not found`)
    return el
  })
  fireEvent.click(option)
}

/** The «Далее» button is disabled until form-options arrive. */
async function waitForForm() {
  const next = await screen.findByRole('button', { name: 'Далее' })
  await waitFor(() => expect(next).toBeEnabled())
  return next
}

let warning: MockInstance
let error: MockInstance

beforeEach(() => {
  // Billing month defaults depend on «today»: pin it (Tashkent: 12 November 2026) without touching timers.
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(new Date('2026-11-12T10:00:00Z'))
  api.getRequestFormOptions.mockReset().mockResolvedValue(formOptions())
  api.listVendors.mockReset().mockResolvedValue(vendorRows)
  api.listContracts.mockReset().mockResolvedValue([])
  api.createPortalRequest.mockReset().mockResolvedValue({ id: 501 })
  api.uploadRequestAttachment.mockReset().mockResolvedValue({})
  warning = vi.spyOn(message, 'warning').mockImplementation(() => undefined as never)
  error = vi.spyOn(message, 'error').mockImplementation(() => undefined as never)
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.useRealTimers()
})

describe('RequestCreatePage form-options', () => {
  it('offers exactly the payment types from form-options', async () => {
    api.getRequestFormOptions.mockResolvedValue(
      formOptions({ payment_types: [paymentType({ payment_type: 'Наличные' }), paymentType({ payment_type: 'Перечисление' })] }),
    )
    renderPage()
    await waitForForm()

    fireEvent.mouseDown(screen.getByText('Выберите тип оплаты'))
    await waitFor(() => expect(document.querySelectorAll('.ant-select-item-option').length).toBe(2))
    const labels = Array.from(document.querySelectorAll('.ant-select-item-option')).map((e) => (e.textContent ?? '').trim())
    expect(labels).toEqual(['Наличные', 'Перечисление'])
  })

  it('warns that the form is not configured and blocks «Далее» when no payment type is enabled', async () => {
    api.getRequestFormOptions.mockResolvedValue(formOptions({ payment_types: [] }))
    renderPage()

    expect(await screen.findByText('Форма не настроена')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Далее' })).toBeDisabled()
  })

  it('shows the error when form-options fail to load', async () => {
    api.getRequestFormOptions.mockRejectedValue(new Error('Сервер недоступен'))
    renderPage()

    expect(await screen.findByText('Сервер недоступен')).toBeInTheDocument()
  })

  it('asks for a payment type before leaving the first step', async () => {
    renderPage()
    fireEvent.click(await waitForForm())

    expect(warning).toHaveBeenCalledWith('Выберите тип оплаты')
    expect(screen.queryByText('Сумма')).toBeNull()
  })

  it('loads vendors of the kind of the chosen type and keeps only vendors allowed for it', async () => {
    api.getRequestFormOptions.mockResolvedValue(formOptions({ payment_types: [paymentType({ vendor_ids: [2] })] }))
    renderPage()
    await waitForForm()
    await pickOption('Выберите тип оплаты', 'Перечисление')
    fireEvent.click(screen.getByRole('button', { name: 'Далее' }))

    await waitFor(() => expect(api.listVendors).toHaveBeenCalledWith({ kind: 'transfer', search: '' }))
    fireEvent.mouseDown(await screen.findByText('Поиск по названию / ИНН'))
    await waitFor(() => expect(document.querySelectorAll('.ant-select-item-option').length).toBe(1))
    expect((document.querySelector('.ant-select-item-option')?.textContent ?? '').trim()).toBe('ООО Лютик')
  })

  it('asks for a vendor kind «cash» for the cash payment type', async () => {
    api.getRequestFormOptions.mockResolvedValue(formOptions({ payment_types: [paymentType({ payment_type: 'Наличные' })] }))
    renderPage()
    await waitForForm()
    await pickOption('Выберите тип оплаты', 'Наличные')
    fireEvent.click(screen.getByRole('button', { name: 'Далее' }))

    await waitFor(() => expect(api.listVendors).toHaveBeenCalledWith({ kind: 'cash', search: '' }))
  })
})

describe('RequestCreatePage requester step', () => {
  it.each([
    ['admin', { is_tenant_admin: true }],
    ['director', { is_tenant_director: true }],
  ])('shows the «Заявитель» step to a tenant %s', async (_role, flags) => {
    api.getRequestFormOptions.mockResolvedValue(formOptions(flags))
    renderPage()

    expect(await screen.findByText('Заявитель')).toBeInTheDocument()
    expect(screen.getByText('Детали')).toBeInTheDocument()
  })

  it('does not show the «Заявитель» step to other roles', async () => {
    renderPage()
    await waitForForm()

    expect(screen.getByText('Тип оплаты', { selector: '.ant-steps-item-title' })).toBeInTheDocument()
    expect(screen.getByText('Детали')).toBeInTheDocument()
    expect(screen.queryByText('Заявитель')).toBeNull()
  })

  it('does not let an admin pass the step when the type has no requesters configured', async () => {
    api.getRequestFormOptions.mockResolvedValue(formOptions({ is_tenant_admin: true }))
    renderPage()
    await waitForForm()
    await pickOption('Выберите тип оплаты', 'Перечисление')
    fireEvent.click(screen.getByRole('button', { name: 'Далее' }))

    expect(await screen.findByText('Для этого типа оплаты не выбраны заявители')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Далее' }))
    expect(warning).toHaveBeenCalledWith(expect.stringContaining('не настроены заявители'))
    expect(screen.queryByText('Сумма')).toBeNull()
  })
})

describe('RequestCreatePage contracts_required', () => {
  const contractRow = (id: number, number: string) => ({ id, contract_number: number, date_from: '2026-01-01', is_expired: false })

  const contractsPt = () =>
    formOptions({
      contracts_module_effective: true,
      payment_types: [
        paymentType({
          contracts_required: true,
          defaults: {
            title: '',
            description: '',
            amount: '1000',
            currency: 'UZS',
            urgency: 'Обычно',
            billing_days_offset: 0,
            payment_purpose: null,
            vendor_ref: 1,
          },
        }),
      ],
    })

  async function goToDetails() {
    renderPage()
    await waitForForm()
    await pickOption('Выберите тип оплаты', 'Перечисление')
    fireEvent.click(screen.getByRole('button', { name: 'Далее' }))
    await screen.findByText('Сумма')
  }

  it('refuses to create without a contract and shows the error', async () => {
    api.getRequestFormOptions.mockResolvedValue(contractsPt())
    api.listContracts.mockResolvedValue([contractRow(10, 'Д-1'), contractRow(11, 'Д-2')])
    await goToDetails()
    await waitFor(() => expect(api.listContracts).toHaveBeenCalledWith({ vendor: 1 }))
    expect(screen.getByText('Договор')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Создать заявку' }))

    await waitFor(() => expect(warning).toHaveBeenCalledWith('Выберите договор'))
    expect(api.createPortalRequest).not.toHaveBeenCalled()
  })

  it('picks the only contract of the vendor and sends it as contract_ref', async () => {
    api.getRequestFormOptions.mockResolvedValue(contractsPt())
    api.listContracts.mockResolvedValue([contractRow(10, 'Д-1')])
    await goToDetails()
    await screen.findByText('Д-1 (2026-01-01)')

    fireEvent.click(screen.getByRole('button', { name: 'Создать заявку' }))

    await waitFor(() => expect(api.createPortalRequest).toHaveBeenCalledTimes(1))
    expect(api.createPortalRequest.mock.calls[0][0]).toMatchObject({ vendor_ref: 1, contract_ref: 10 })
  })

  it('hides the contract field when the contracts module is off for the tenant', async () => {
    api.getRequestFormOptions.mockResolvedValue({ ...contractsPt(), contracts_module_effective: false })
    await goToDetails()

    expect(screen.queryByText('Договор')).toBeNull()
    expect(api.listContracts).not.toHaveBeenCalled()
  })
})

describe('RequestCreatePage submit', () => {
  it('sends the payload built from the type defaults and opens the new request with justCreated', async () => {
    api.getRequestFormOptions.mockResolvedValue(
      formOptions({
        payment_types: [
          paymentType({
            payment_purposes: [{ name: 'Аренда', category: 'Офис' }],
            defaults: {
              title: 'Аренда офиса',
              description: 'Оплата аренды',
              amount: '150000',
              currency: 'UZS',
              urgency: 'Срочно',
              billing_days_offset: 1,
              payment_purpose: 'Аренда',
              vendor_ref: 5,
            },
          }),
        ],
      }),
    )
    renderPage()
    await waitForForm()
    await pickOption('Выберите тип оплаты', 'Перечисление')
    fireEvent.click(screen.getByRole('button', { name: 'Далее' }))
    await screen.findByText('Сумма')

    fireEvent.click(screen.getByRole('button', { name: 'Создать заявку' }))

    await waitFor(() => expect(api.createPortalRequest).toHaveBeenCalledTimes(1))
    expect(api.createPortalRequest.mock.calls[0][0]).toEqual({
      title: 'Аренда офиса',
      description: 'Оплата аренды',
      amount: 150000,
      currency: 'UZS',
      payment_type: 'Перечисление',
      urgency: 'Срочно',
      billing_date: '2026-12-01',
      status: 'DRAFT',
      amortization_months: 1,
      payment_purpose: 'Аренда',
      vendor_ref: 5,
    })
    expect(api.uploadRequestAttachment).not.toHaveBeenCalled()
    expect((await screen.findByTestId('detail')).textContent).toBe('id=501 state={"justCreated":true}')
  })

  it('sends the chosen requester, a typed amount and a vendor picked from the directory', async () => {
    api.getRequestFormOptions.mockResolvedValue(
      formOptions({
        is_tenant_admin: true,
        payment_types: [paymentType({ requesters: [{ id: 3, username: 'ivan' }], requester_ids: [3] })],
      }),
    )
    renderPage()
    await waitForForm()
    await pickOption('Выберите тип оплаты', 'Перечисление')
    fireEvent.click(screen.getByRole('button', { name: 'Далее' }))
    await pickOption('Выберите заявителя', 'ivan')
    fireEvent.click(screen.getByRole('button', { name: 'Далее' }))
    await screen.findByText('Сумма')

    const amount = screen.getByRole('spinbutton')
    fireEvent.change(amount, { target: { value: '75000' } })
    fireEvent.blur(amount)
    await pickOption('Поиск по названию / ИНН', 'ООО Лютик')
    fireEvent.click(screen.getByRole('button', { name: 'Создать заявку' }))

    await waitFor(() => expect(api.createPortalRequest).toHaveBeenCalledTimes(1))
    expect(api.createPortalRequest.mock.calls[0][0]).toEqual({
      title: 'Заявка',
      description: '',
      amount: 75000,
      currency: 'UZS',
      payment_type: 'Перечисление',
      urgency: 'Обычно',
      billing_date: '2026-11-01',
      status: 'DRAFT',
      amortization_months: 1,
      requester: 3,
      vendor_ref: 2,
    })
    expect((await screen.findByTestId('detail')).textContent).toBe('id=501 state={"justCreated":true}')
  })

  it('does not call the API without an amount', async () => {
    renderPage()
    await waitForForm()
    await pickOption('Выберите тип оплаты', 'Перечисление')
    fireEvent.click(screen.getByRole('button', { name: 'Далее' }))
    await screen.findByText('Сумма')

    fireEvent.click(screen.getByRole('button', { name: 'Создать заявку' }))

    expect(warning).toHaveBeenCalledWith('Укажите сумму')
    expect(api.createPortalRequest).not.toHaveBeenCalled()
  })

  it('shows the API error and stays on the form when creation fails', async () => {
    api.getRequestFormOptions.mockResolvedValue(
      formOptions({
        payment_types: [
          paymentType({
            defaults: {
              title: '',
              description: '',
              amount: '1000',
              currency: 'UZS',
              urgency: 'Обычно',
              billing_days_offset: 0,
              payment_purpose: null,
              vendor_ref: 5,
            },
          }),
        ],
      }),
    )
    api.createPortalRequest.mockRejectedValue(new Error('Лимит превышен'))
    renderPage()
    await waitForForm()
    await pickOption('Выберите тип оплаты', 'Перечисление')
    fireEvent.click(screen.getByRole('button', { name: 'Далее' }))
    await screen.findByText('Сумма')

    fireEvent.click(screen.getByRole('button', { name: 'Создать заявку' }))

    await waitFor(() => expect(error).toHaveBeenCalledWith('Лимит превышен'))
    expect(screen.queryByTestId('detail')).toBeNull()
    // The button drops its loading state (and the «loading» icon in its name) once the request settles.
    expect(await screen.findByRole('button', { name: 'Создать заявку' })).toBeInTheDocument()
  })
})
