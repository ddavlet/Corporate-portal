import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import dayjs from 'dayjs'
import timezone from 'dayjs/plugin/timezone'
import utc from 'dayjs/plugin/utc'
import { message, theme } from 'antd'
import { MemoryRouter, Route, Routes, useLocation, useNavigate, useParams, type NavigateFunction } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest'
import type { RequestFormOptionsPaymentType, RequestFormOptionsResponse } from '../../lib/api'
import { resetViewport, setViewport, type ViewportKind } from '../../test/viewport'
import stylesSource from '../../styles.css?raw'
import { RequestCreateRoute } from './RequestCreateRoute'

// main.tsx extends dayjs in the app; the billing month defaults need .tz() (tashkentTime).
dayjs.extend(utc)
dayjs.extend(timezone)

const api = vi.hoisted(() => ({
  getRequestFormOptions: vi.fn(),
  listVendors: vi.fn(),
  listVendorsPage: vi.fn(),
  listContracts: vi.fn(),
  createVendor: vi.fn(),
  createContract: vi.fn(),
  createPortalRequest: vi.fn(),
  uploadRequestAttachment: vi.fn(),
}))

vi.mock('../../lib/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../lib/api')>()),
  getRequestFormOptions: (...a: unknown[]) => api.getRequestFormOptions(...a),
  listVendors: (...a: unknown[]) => api.listVendors(...a),
  listVendorsPage: (...a: unknown[]) => api.listVendorsPage(...a),
  listContracts: (...a: unknown[]) => api.listContracts(...a),
  createVendor: (...a: unknown[]) => api.createVendor(...a),
  createContract: (...a: unknown[]) => api.createContract(...a),
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

type VendorRow = { id: number; tenant: number; kind: string; name: string; inn: string | null; created_at: string; created_by: number }

const vendor = (id: number, name: string, inn: string | null = null): VendorRow => ({
  id,
  tenant: 1,
  kind: 'transfer',
  name,
  inn,
  created_at: '',
  created_by: 1,
})

let vendorRows: VendorRow[] = []

function DetailProbe() {
  const { id } = useParams()
  const state = useLocation().state
  return <div data-testid="detail">{`id=${id} state=${JSON.stringify(state)}`}</div>
}

/** The router's navigate, to press the system «Назад» (`historyBack`) as a phone gesture or the browser does. */
let routerNavigate: NavigateFunction | null = null
function NavigateProbe() {
  routerNavigate = useNavigate()
  return null
}
function historyBack() {
  act(() => {
    void routerNavigate?.(-1)
  })
}

function renderWizard(viewport: ViewportKind = 'phone') {
  setViewport(viewport)
  return render(
    <MemoryRouter initialEntries={['/requests', '/requests/new']} initialIndex={1}>
      <NavigateProbe />
      <Routes>
        <Route path="/requests" element={<div data-testid="list">Список</div>} />
        <Route path="/requests/new" element={<RequestCreateRoute />} />
        <Route path="/requests/:id" element={<DetailProbe />} />
      </Routes>
    </MemoryRouter>,
  )
}

function stepTitles() {
  return within(screen.getByRole('navigation', { name: 'Шаги' }))
    .getAllByRole('listitem')
    .map((li) => (li.textContent ?? '').trim())
}

async function chooseType(name = 'Перечисление') {
  fireEvent.click(await screen.findByRole('radio', { name }))
}

function next() {
  fireEvent.click(screen.getByRole('button', { name: 'Далее' }))
}

async function goToDetails() {
  await chooseType()
  next()
  return screen.findByLabelText('Сумма')
}

let warning: MockInstance

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(new Date('2026-11-12T10:00:00Z'))
  vendorRows = [vendor(1, 'ООО Ромашка', '123456789'), vendor(2, 'ООО Лютик')]
  api.getRequestFormOptions.mockReset().mockResolvedValue(formOptions())
  api.listVendors.mockReset().mockImplementation(async () => vendorRows)
  api.listVendorsPage.mockReset().mockImplementation(async () => vendorRows)
  api.listContracts.mockReset().mockResolvedValue([])
  api.createVendor.mockReset()
  api.createContract.mockReset()
  api.createPortalRequest.mockReset().mockResolvedValue({ id: 501 })
  api.uploadRequestAttachment.mockReset().mockResolvedValue({})
  warning = vi.spyOn(message, 'warning').mockImplementation(() => undefined as never)
  vi.spyOn(message, 'error').mockImplementation(() => undefined as never)
  vi.spyOn(message, 'success').mockImplementation(() => undefined as never)
})

afterEach(() => {
  resetViewport()
  vi.restoreAllMocks()
  vi.useRealTimers()
})

describe('RequestCreateRoute', () => {
  it('opens the full-screen wizard on a phone', async () => {
    const { container } = renderWizard('phone')

    expect(await screen.findByRole('radio', { name: 'Перечисление' })).toBeInTheDocument()
    expect(container.querySelector('.m-fullscreen')).not.toBeNull()
    expect(screen.getByRole('heading', { name: 'Новая заявка' })).toBeInTheDocument()
    expect(container.querySelector('.ant-steps')).toBeNull()
  })

  it('keeps the desktop form on a desktop', async () => {
    const { container } = renderWizard('desktop')

    expect(await screen.findByRole('button', { name: 'К списку заявок' })).toBeInTheDocument()
    expect(container.querySelector('.ant-steps')).not.toBeNull()
    expect(screen.queryByTestId('request-create-mobile')).toBeNull()
    expect(container.querySelector('.m-fullscreen')).toBeNull()
  })
})

describe('RequestCreateMobilePage steps', () => {
  it('shows two steps and «Закрыть» to a user who is not an admin or a director', async () => {
    renderWizard()
    await chooseType()

    expect(stepTitles()).toEqual(['Тип оплаты', 'Детали'])
    fireEvent.click(screen.getByRole('button', { name: 'Закрыть' }))
    expect(await screen.findByTestId('list')).toBeInTheDocument()
  })

  it('shows the «Заявитель» step to an admin, with its error under the field and a picker', async () => {
    api.getRequestFormOptions.mockResolvedValue(
      formOptions({
        is_tenant_admin: true,
        payment_types: [paymentType({ requesters: [{ id: 3, username: 'ivan' }, { id: 4, username: 'olga' }], requester_ids: [3, 4] })],
      }),
    )
    renderWizard()
    await chooseType()

    expect(stepTitles()).toEqual(['Тип оплаты', 'Заявитель', 'Детали'])
    next()
    const field = await screen.findByRole('button', { name: 'Заявитель: Выберите заявителя' })
    // «Назад» instead of «Закрыть» from the second step on.
    expect(screen.getByRole('button', { name: 'Назад' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Закрыть' })).toBeNull()

    next()
    expect(warning).toHaveBeenCalledWith('Выберите заявителя')
    expect(field).toHaveAttribute('aria-invalid', 'true')
    expect(field).toHaveAccessibleDescription('Выберите заявителя')

    fireEvent.click(field)
    fireEvent.click(within(await screen.findByRole('list', { name: 'Заявитель' })).getByRole('button', { name: 'olga' }))
    expect(await screen.findByRole('button', { name: 'Заявитель: olga' })).not.toHaveAttribute('aria-invalid')

    next()
    expect(await screen.findByLabelText('Сумма')).toBeInTheDocument()
  })

  it('asks for a payment type under the field', async () => {
    renderWizard()
    await screen.findByRole('radio', { name: 'Перечисление' })
    next()

    expect(warning).toHaveBeenCalledWith('Выберите тип оплаты')
    expect(screen.getByRole('radiogroup', { name: 'Тип оплаты' })).toHaveAccessibleDescription('Выберите тип оплаты')
  })

  it('shows the error of form-options with a retry', async () => {
    api.getRequestFormOptions.mockRejectedValueOnce(new Error('Сервер недоступен'))
    renderWizard()

    expect(await screen.findByText('Сервер недоступен')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Повторить/ }))
    expect(await screen.findByRole('radio', { name: 'Перечисление' })).toBeInTheDocument()
    expect(api.getRequestFormOptions).toHaveBeenCalledTimes(2)
  })
})

describe('RequestCreateMobilePage vendor and contract', () => {
  it('keeps the typed fields when a vendor is picked and opens the new request’s card', async () => {
    renderWizard()
    const amount = await goToDetails()
    fireEvent.change(amount, { target: { value: '75000' } })
    fireEvent.blur(amount)
    fireEvent.change(screen.getByLabelText('Описание'), { target: { value: 'Оплата за ноябрь' } })

    fireEvent.click(screen.getByRole('button', { name: 'Поставщик: Выберите поставщика' }))
    const list = await screen.findByRole('list', { name: 'Поставщик' })
    // One request of PICKER_PAGE_SIZE rows, not every page of the directory.
    expect(api.listVendorsPage).toHaveBeenLastCalledWith({ kind: 'transfer', search: '', page_size: 200 })
    fireEvent.click(within(list).getByRole('button', { name: 'ООО Лютик' }))

    expect(await screen.findByRole('button', { name: 'Поставщик: ООО Лютик' })).toBeInTheDocument()
    expect(screen.getByLabelText('Сумма')).toHaveValue('75000')
    expect(screen.getByLabelText('Описание')).toHaveValue('Оплата за ноябрь')

    fireEvent.click(screen.getByRole('button', { name: /Создать заявку/ }))

    await waitFor(() => expect(api.createPortalRequest).toHaveBeenCalledTimes(1))
    expect(api.createPortalRequest.mock.calls[0][0]).toEqual({
      title: 'Заявка',
      description: 'Оплата за ноябрь',
      amount: 75000,
      currency: 'UZS',
      payment_type: 'Перечисление',
      urgency: 'Обычно',
      billing_date: '2026-11-01',
      status: 'DRAFT',
      amortization_months: 1,
      vendor_ref: 2,
    })
    expect((await screen.findByTestId('detail')).textContent).toBe('id=501 state={"justCreated":true}')
  })

  it('shows the missing vendor and amount under their fields and does not create', async () => {
    renderWizard()
    await goToDetails()

    fireEvent.click(screen.getByRole('button', { name: /Создать заявку/ }))

    expect(warning).toHaveBeenCalledWith('Укажите сумму')
    expect(screen.getByLabelText('Сумма')).toHaveAccessibleDescription('Укажите сумму')
    expect(screen.getByRole('button', { name: 'Поставщик: Выберите поставщика' })).toHaveAccessibleDescription(
      'Выберите поставщика из справочника',
    )
    expect(api.createPortalRequest).not.toHaveBeenCalled()
  })

  it('shows «Выберите договор» under the contract and creates once a contract is picked', async () => {
    api.getRequestFormOptions.mockResolvedValue(
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
      }),
    )
    api.listContracts.mockResolvedValue([
      { id: 10, contract_number: 'Д-1', date_from: '2026-01-01', is_expired: false },
      { id: 11, contract_number: 'Д-2', date_from: '2026-02-01', is_expired: false },
    ])
    renderWizard()
    await goToDetails()
    const contract = await screen.findByRole('button', { name: 'Договор: Выберите договор' })
    expect(api.listContracts).toHaveBeenCalledWith({ vendor: 1 })

    fireEvent.click(screen.getByRole('button', { name: /Создать заявку/ }))

    await waitFor(() => expect(warning).toHaveBeenCalledWith('Выберите договор'))
    expect(contract).toHaveAttribute('aria-invalid', 'true')
    expect(contract).toHaveAccessibleDescription('Выберите договор')
    expect(api.createPortalRequest).not.toHaveBeenCalled()

    fireEvent.click(contract)
    fireEvent.click(
      within(await screen.findByRole('list', { name: 'Договор' })).getByRole('button', { name: 'Д-2 (2026-02-01)' }),
    )
    expect(await screen.findByRole('button', { name: 'Договор: Д-2 (2026-02-01)' })).not.toHaveAttribute('aria-invalid')

    fireEvent.click(screen.getByRole('button', { name: /Создать заявку/ }))
    await waitFor(() => expect(api.createPortalRequest).toHaveBeenCalledTimes(1))
    expect(api.createPortalRequest.mock.calls[0][0]).toMatchObject({ vendor_ref: 1, contract_ref: 11, amount: 1000 })
  })

  it('creates a new vendor from the picker’s search and picks it', async () => {
    api.createVendor.mockImplementation(async (body: { name: string; inn?: string }) => {
      const row = vendor(9, body.name, body.inn ?? null)
      vendorRows = [...vendorRows, row]
      return row
    })
    renderWizard()
    const amount = await goToDetails()
    fireEvent.change(amount, { target: { value: '5000' } })
    fireEvent.blur(amount)

    fireEvent.click(screen.getByRole('button', { name: 'Поставщик: Выберите поставщика' }))
    await screen.findByRole('list', { name: 'Поставщик' })
    fireEvent.change(screen.getByRole('textbox', { name: 'Поиск по названию / ИНН' }), { target: { value: 'ООО Новый' } })
    fireEvent.click(screen.getByRole('button', { name: 'Новый поставщик' }))

    const name = await screen.findByLabelText('Наименование')
    expect(name).toHaveValue('ООО Новый')
    fireEvent.click(screen.getByRole('button', { name: /^(loading )?Сохранить$/ }))
    expect(warning).toHaveBeenCalledWith('ИНН обязателен для перечисления')
    expect(screen.getByLabelText('ИНН')).toHaveAccessibleDescription('ИНН обязателен для перечисления')
    expect(api.createVendor).not.toHaveBeenCalled()

    fireEvent.change(screen.getByLabelText('ИНН'), { target: { value: '305123456' } })
    fireEvent.click(screen.getByRole('button', { name: /^(loading )?Сохранить$/ }))

    await waitFor(() =>
      expect(api.createVendor).toHaveBeenCalledWith({
        kind: 'transfer',
        name: 'ООО Новый',
        inn: '305123456',
        account_number: undefined,
      }),
    )
    expect(await screen.findByRole('button', { name: 'Поставщик: ООО Новый (ИНН 305123456)' })).toBeInTheDocument()
    expect(screen.getByLabelText('Сумма')).toHaveValue('5000')

    fireEvent.click(screen.getByRole('button', { name: /Создать заявку/ }))
    await waitFor(() => expect(api.createPortalRequest).toHaveBeenCalledTimes(1))
    expect(api.createPortalRequest.mock.calls[0][0]).toMatchObject({ vendor_ref: 9, amount: 5000 })
  })
})

describe('RequestCreateMobilePage navigation and submit', () => {
  it('keeps the typed fields when going «Назад» and forward again', async () => {
    renderWizard()
    const amount = await goToDetails()
    fireEvent.change(amount, { target: { value: '1200' } })
    fireEvent.blur(amount)

    fireEvent.click(screen.getByRole('button', { name: 'Назад' }))
    expect(await screen.findByRole('radio', { name: 'Перечисление' })).toHaveAttribute('aria-checked', 'true')
    expect(screen.getByRole('button', { name: 'Закрыть' })).toBeInTheDocument()

    next()
    expect(await screen.findByLabelText('Сумма')).toHaveValue('1200')
  })

  it('sends the picked requester of an admin', async () => {
    api.getRequestFormOptions.mockResolvedValue(
      formOptions({
        is_tenant_admin: true,
        payment_types: [paymentType({ requesters: [{ id: 3, username: 'ivan' }, { id: 4, username: 'olga' }], requester_ids: [3, 4] })],
      }),
    )
    renderWizard()
    await chooseType()
    next()
    fireEvent.click(await screen.findByRole('button', { name: 'Заявитель: Выберите заявителя' }))
    fireEvent.click(within(await screen.findByRole('list', { name: 'Заявитель' })).getByRole('button', { name: 'olga' }))
    await screen.findByRole('button', { name: 'Заявитель: olga' })
    next()
    const amount = await screen.findByLabelText('Сумма')
    fireEvent.change(amount, { target: { value: '10' } })
    fireEvent.blur(amount)
    fireEvent.click(screen.getByRole('button', { name: 'Поставщик: Выберите поставщика' }))
    fireEvent.click(within(await screen.findByRole('list', { name: 'Поставщик' })).getByRole('button', { name: 'ООО Лютик' }))
    await screen.findByRole('button', { name: 'Поставщик: ООО Лютик' })

    fireEvent.click(screen.getByRole('button', { name: /Создать заявку/ }))

    await waitFor(() => expect(api.createPortalRequest).toHaveBeenCalledTimes(1))
    expect(api.createPortalRequest.mock.calls[0][0]).toMatchObject({ requester: 4, vendor_ref: 2, amount: 10 })
  })

  it('stays on the form with its values when the server refuses the request', async () => {
    api.createPortalRequest.mockRejectedValue(new Error('Лимит превышен'))
    const error = vi.spyOn(message, 'error')
    renderWizard()
    const amount = await goToDetails()
    fireEvent.change(amount, { target: { value: '300' } })
    fireEvent.blur(amount)
    fireEvent.click(screen.getByRole('button', { name: 'Поставщик: Выберите поставщика' }))
    fireEvent.click(within(await screen.findByRole('list', { name: 'Поставщик' })).getByRole('button', { name: 'ООО Лютик' }))
    await screen.findByRole('button', { name: 'Поставщик: ООО Лютик' })

    fireEvent.click(screen.getByRole('button', { name: /Создать заявку/ }))

    await waitFor(() => expect(error).toHaveBeenCalledWith('Лимит превышен'))
    expect(screen.queryByTestId('detail')).toBeNull()
    expect(screen.getByLabelText('Сумма')).toHaveValue('300')
    expect(screen.getByRole('button', { name: /Создать заявку/ })).toBeEnabled()
  })

  it('asks for the required fields of «Новый договор» under them and does not save', async () => {
    api.getRequestFormOptions.mockResolvedValue(
      formOptions({
        contracts_module_effective: true,
        payment_types: [
          paymentType({
            contracts_required: true,
            defaults: {
              title: '', description: '', amount: '1000', currency: 'UZS', urgency: 'Обычно',
              billing_days_offset: 0, payment_purpose: null, vendor_ref: 1,
            },
          }),
        ],
      }),
    )
    renderWizard()
    await goToDetails()
    fireEvent.click(await screen.findByRole('button', { name: 'Договор: Выберите договор' }))
    await screen.findByRole('list', { name: 'Договор' })
    fireEvent.click(screen.getByRole('button', { name: 'Новый договор' }))

    expect(await screen.findByLabelText('Номер договора')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /^(loading )?Сохранить$/ }))

    expect(warning).toHaveBeenCalled()
    expect(screen.getByLabelText('Номер договора')).toHaveAttribute('aria-invalid', 'true')
    expect(api.createContract).not.toHaveBeenCalled()
  })
})

function deferred<T>() {
  let resolve!: (v: T) => void
  let reject!: (e: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

const contractTypeOptions = () =>
  formOptions({
    contracts_module_effective: true,
    payment_types: [
      paymentType({
        contracts_required: true,
        defaults: {
          title: '', description: '', amount: '1000', currency: 'UZS', urgency: 'Обычно',
          billing_days_offset: 0, payment_purpose: null, vendor_ref: 1,
        },
      }),
    ],
  })

describe('RequestCreateMobilePage review fixes', () => {
  it('keeps the contract field closed while contracts load, then lists them in the picker', async () => {
    api.getRequestFormOptions.mockResolvedValue(contractTypeOptions())
    const pending = deferred<unknown[]>()
    api.listContracts.mockReturnValueOnce(pending.promise).mockResolvedValue([
      { id: 10, contract_number: 'Д-1', date_from: '2026-01-01', is_expired: false },
      { id: 11, contract_number: 'Д-2', date_from: '2026-02-01', is_expired: false },
    ])
    renderWizard()
    await goToDetails()

    const loading = await screen.findByRole('button', { name: 'Договор: Загружаем договоры…' })
    expect(loading).toBeDisabled()

    await act(async () => {
      pending.resolve([
        { id: 10, contract_number: 'Д-1', date_from: '2026-01-01', is_expired: false },
        { id: 11, contract_number: 'Д-2', date_from: '2026-02-01', is_expired: false },
      ])
    })
    const contract = await screen.findByRole('button', { name: 'Договор: Выберите договор' })
    expect(contract).toBeEnabled()
    fireEvent.click(contract)
    const list = await screen.findByRole('list', { name: 'Договор' })
    expect(within(list).getByRole('button', { name: 'Д-2 (2026-02-01)' })).toBeInTheDocument()
    expect(screen.queryByText('Договоров с этим поставщиком нет')).toBeNull()
  })

  it('shows an error with a retry in the contract picker instead of «no contracts»', async () => {
    api.getRequestFormOptions.mockResolvedValue(contractTypeOptions())
    api.listContracts
      .mockRejectedValueOnce(new Error('Сеть'))
      .mockRejectedValueOnce(new Error('Сеть'))
      .mockResolvedValue([{ id: 10, contract_number: 'Д-1', date_from: '2026-01-01', is_expired: false }])
    renderWizard()
    await goToDetails()

    const contract = await screen.findByRole('button', {
      name: 'Договор: Не удалось загрузить договоры, откройте ещё раз',
    })
    fireEvent.click(contract)
    const retry = await screen.findByRole('button', { name: /Повторить/ })
    expect(screen.queryByText('Договоров с этим поставщиком нет')).toBeNull()

    fireEvent.click(retry)
    const list = await screen.findByRole('list', { name: 'Договор' })
    expect(within(list).getByRole('button', { name: 'Д-1 (2026-01-01)' })).toBeInTheDocument()
  })

  it('shows the name of a new vendor that is outside the vendors allowed for the type', async () => {
    api.getRequestFormOptions.mockResolvedValue(formOptions({ payment_types: [paymentType({ vendor_ids: [1, 2] })] }))
    api.createVendor.mockImplementation(async (body: { name: string; inn?: string }) => {
      const row = vendor(9, body.name, body.inn ?? null)
      vendorRows = [...vendorRows, row]
      return row
    })
    renderWizard()
    await goToDetails()

    fireEvent.click(screen.getByRole('button', { name: 'Поставщик: Выберите поставщика' }))
    await screen.findByRole('list', { name: 'Поставщик' })
    fireEvent.click(screen.getByRole('button', { name: 'Новый поставщик' }))
    fireEvent.change(await screen.findByLabelText('Наименование'), { target: { value: 'ООО Свежий' } })
    fireEvent.change(screen.getByLabelText('ИНН'), { target: { value: '301000000' } })
    fireEvent.click(screen.getByRole('button', { name: /^(loading )?Сохранить$/ }))

    expect(await screen.findByRole('button', { name: 'Поставщик: ООО Свежий (ИНН 301000000)' })).toBeInTheDocument()
  })

  it('links the error of «Назначение платежа» to its field', async () => {
    api.getRequestFormOptions.mockResolvedValue(
      formOptions({ payment_types: [paymentType({ payment_purposes: [{ name: 'Аренда', category: 'Офис' }] })] }),
    )
    renderWizard()
    await goToDetails()
    const purpose = screen.getByLabelText('Назначение платежа')
    expect(purpose).not.toHaveAttribute('aria-invalid')

    fireEvent.click(screen.getByRole('button', { name: /Создать заявку/ }))

    await waitFor(() => expect(screen.getByLabelText('Назначение платежа')).toHaveAttribute('aria-invalid', 'true'))
    expect(screen.getByLabelText('Назначение платежа')).toHaveAccessibleDescription('Выберите назначение платежа')
    // The billing month is valid by default: no error is announced on it.
    expect(screen.getByLabelText('Месяц биллинга')).not.toHaveAttribute('aria-invalid')
  })

  it('opens the details of another payment type without the errors of a refused submit', async () => {
    api.getRequestFormOptions.mockResolvedValue(
      formOptions({ payment_types: [paymentType(), paymentType({ payment_type: 'Наличные' })] }),
    )
    renderWizard()
    await goToDetails()
    fireEvent.click(screen.getByRole('button', { name: /Создать заявку/ }))
    await waitFor(() => expect(screen.getByLabelText('Сумма')).toHaveAttribute('aria-invalid', 'true'))

    fireEvent.click(screen.getByRole('button', { name: 'Назад' }))
    await chooseType('Наличные')
    next()

    const amount = await screen.findByLabelText('Сумма')
    expect(amount).not.toHaveAttribute('aria-invalid')
    expect(screen.getByRole('button', { name: 'Поставщик: Выберите поставщика' })).not.toHaveAttribute('aria-invalid')
  })

  it('shows the instruction of an empty picker field in the secondary text colour', async () => {
    renderWizard()
    await goToDetails()
    const text = within(screen.getByRole('button', { name: 'Поставщик: Выберите поставщика' })).getByText(
      'Выберите поставщика',
    )
    expect(text).toHaveStyle({ color: theme.getDesignToken().colorTextSecondary })
  })

  it('makes the fields of sheets and pickers 16 px, so iOS does not zoom in', () => {
    const css = stylesSource.replace(/\/\*[\s\S]*?\*\//g, '')
    const rule = /([^{}]+)\{\s*font-size:\s*16px;?\s*\}/.exec(css)
    const selectors = (rule?.[1] ?? '').split(',').map((sel) => sel.trim())
    expect(selectors).toEqual(expect.arrayContaining(['.m-root input', '.m-sheet input', '.m-sheet textarea', '.m-picker input']))
  })
})

describe('RequestCreateMobilePage system «Назад»', () => {
  it('closes the picker, then goes a step back, then leaves the wizard', async () => {
    renderWizard()
    const amount = await goToDetails()
    fireEvent.change(amount, { target: { value: '4200' } })
    fireEvent.blur(amount)

    fireEvent.click(screen.getByRole('button', { name: 'Поставщик: Выберите поставщика' }))
    await screen.findByRole('list', { name: 'Поставщик' })

    historyBack()
    await waitFor(() => expect(screen.queryByRole('list', { name: 'Поставщик' })).toBeNull())
    expect(screen.getByLabelText('Сумма')).toHaveValue('4200')

    historyBack()
    expect(await screen.findByRole('radio', { name: 'Перечисление' })).toHaveAttribute('aria-checked', 'true')
    expect(screen.queryByTestId('list')).toBeNull()

    next()
    expect(await screen.findByLabelText('Сумма')).toHaveValue('4200')
    historyBack()
    await screen.findByRole('radio', { name: 'Перечисление' })
    historyBack()
    expect(await screen.findByTestId('list')).toBeInTheDocument()
  })

  it('needs one «Назад» from the first step after the wizard’s own «Назад»', async () => {
    renderWizard()
    await goToDetails()
    fireEvent.click(screen.getByRole('button', { name: 'Назад' }))
    await screen.findByRole('button', { name: 'Закрыть' })

    historyBack()
    expect(await screen.findByTestId('list')).toBeInTheDocument()
  })

  it('leads from the new request’s card back to the list, not to the wizard', async () => {
    renderWizard()
    const amount = await goToDetails()
    fireEvent.change(amount, { target: { value: '10' } })
    fireEvent.blur(amount)
    fireEvent.click(screen.getByRole('button', { name: 'Поставщик: Выберите поставщика' }))
    fireEvent.click(within(await screen.findByRole('list', { name: 'Поставщик' })).getByRole('button', { name: 'ООО Лютик' }))
    await screen.findByRole('button', { name: 'Поставщик: ООО Лютик' })
    fireEvent.click(screen.getByRole('button', { name: /Создать заявку/ }))

    expect((await screen.findByTestId('detail')).textContent).toBe('id=501 state={"justCreated":true}')
    historyBack()
    expect(await screen.findByTestId('list')).toBeInTheDocument()
  })
})
