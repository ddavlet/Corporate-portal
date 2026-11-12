import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import dayjs from 'dayjs'
import timezone from 'dayjs/plugin/timezone'
import utc from 'dayjs/plugin/utc'
import { MemoryRouter, Route, Routes, useLocation, useParams } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { resetViewport, setViewport, type ViewportKind } from '../../test/viewport'
import { RequestCreateRoute } from '../requests/RequestCreateRoute'
import { TgRequestCreatePage } from './TgRequestCreatePage'

dayjs.extend(utc)
dayjs.extend(timezone)

// Characterization of the Mini App create form BEFORE the portal gets a phone wizard: /tg/requests/new keeps its own
// tg-* markup at any width and never turns into the portal's full-screen phone flow.

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

const options = {
  is_tenant_admin: false,
  is_tenant_director: false,
  contracts_module_effective: false,
  payment_types: [
    {
      payment_type: 'Перечисление',
      requester_ids: [],
      requesters: [],
      vendor_ids: [],
      payment_purposes: [],
      defaults: {
        title: 'Аренда офиса',
        description: 'Оплата аренды',
        amount: '150000',
        currency: 'UZS',
        urgency: 'Срочно',
        billing_days_offset: 1,
        payment_purpose: null,
        vendor_ref: 5,
      },
    },
  ],
}

function DetailProbe() {
  const { id } = useParams()
  const state = useLocation().state
  return <div data-testid="detail">{`id=${id} state=${JSON.stringify(state)}`}</div>
}

function renderTgPage() {
  return render(
    <MemoryRouter initialEntries={['/tg/requests/new']}>
      <Routes>
        <Route path="/tg/requests/new" element={<TgRequestCreatePage />} />
        <Route path="/tg/requests/:id" element={<DetailProbe />} />
      </Routes>
    </MemoryRouter>,
  )
}

async function waitForForm() {
  const next = await screen.findByRole('button', { name: 'Далее' })
  await waitFor(() => expect(next).toBeEnabled())
}

async function pickPaymentType(label: string) {
  fireEvent.mouseDown(screen.getByText('Выберите тип оплаты'))
  const option = await waitFor(() => {
    const el = Array.from(document.querySelectorAll('.ant-select-item-option')).find(
      (e) => (e.textContent ?? '').trim() === label,
    )
    if (!el) throw new Error(`option ${label} not found`)
    return el
  })
  fireEvent.click(option)
}

describe.each<ViewportKind>(['phone', 'desktop'])('TgRequestCreatePage on a %s', (viewport) => {
  beforeEach(() => {
    setViewport(viewport)
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-11-12T10:00:00Z'))
    api.getRequestFormOptions.mockReset().mockResolvedValue(options)
    api.listVendors.mockReset().mockResolvedValue([])
    api.listContracts.mockReset().mockResolvedValue([])
    api.createPortalRequest.mockReset().mockResolvedValue({ id: 501 })
    api.uploadRequestAttachment.mockReset().mockResolvedValue({})
  })

  afterEach(() => {
    resetViewport()
    vi.useRealTimers()
  })

  it('keeps the Mini App markup and no portal full-screen phone flow', async () => {
    const { container } = renderTgPage()
    await waitForForm()

    expect(container.querySelector('.tg-create-page')).not.toBeNull()
    expect(container.querySelector('.tg-steps')).not.toBeNull()
    expect(container.querySelector('.tg-field-block')).not.toBeNull()
    expect(container.querySelector('.tg-sticky-actions')).not.toBeNull()
    expect(document.querySelector('.m-fullscreen')).toBeNull()
  })

  it('keeps the Mini App markup on the details step too', async () => {
    const { container } = renderTgPage()
    await waitForForm()
    await pickPaymentType('Перечисление')
    fireEvent.click(screen.getByRole('button', { name: 'Далее' }))
    await screen.findByText('Сумма')

    expect(container.querySelectorAll('.tg-field-block').length).toBeGreaterThan(3)
    expect(container.querySelector('.tg-create-page')).not.toBeNull()
    expect(document.querySelector('.m-fullscreen')).toBeNull()
  })

  it('creates the request and opens /tg/requests/{id} with justCreated', async () => {
    renderTgPage()
    await waitForForm()
    await pickPaymentType('Перечисление')
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
      vendor_ref: 5,
    })
    expect((await screen.findByTestId('detail')).textContent).toBe('id=501 state={"justCreated":true}')
  })
})

describe('the portal create route inside the Mini App on a phone', () => {
  beforeEach(() => {
    setViewport('phone')
    // The page runs under /tg/: the one switch of the mobile layout (usePortalMobileMode) reads the address.
    window.history.pushState({}, '', '/tg/requests/new')
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-11-12T10:00:00Z'))
    api.getRequestFormOptions.mockReset().mockResolvedValue(options)
    api.listVendors.mockReset().mockResolvedValue([])
    api.listContracts.mockReset().mockResolvedValue([])
  })

  afterEach(() => {
    window.history.pushState({}, '', '/')
    resetViewport()
    vi.useRealTimers()
  })

  it('never turns into the portal full-screen wizard', async () => {
    render(
      <MemoryRouter initialEntries={['/tg/requests/new']}>
        <Routes>
          <Route path="/tg/requests/new" element={<RequestCreateRoute />} />
        </Routes>
      </MemoryRouter>,
    )
    await waitForForm()

    expect(screen.queryByTestId('request-create-mobile')).toBeNull()
    expect(document.querySelector('.m-fullscreen')).toBeNull()
  })
})
