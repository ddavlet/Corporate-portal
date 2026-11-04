import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { TgInvestmentsCollectPage } from './TgInvestmentsCollectPage'
import { TgInvestmentsProjectsPage } from './TgInvestmentsProjectsPage'

const getFundingPoolMock = vi.fn()
const createFromRequestsMock = vi.fn()
const getFormConfigMock = vi.fn()
const getCompaniesMock = vi.fn()
const getProjectInvestmentsMock = vi.fn()
const getFundingConfigMock = vi.fn()

vi.mock('../../lib/api', () => ({
  DEFAULT_INVESTMENT_FORM_CONFIG: { uses_companies: false },
  getFundingPool: (...a: unknown[]) => getFundingPoolMock(...a),
  createInvestmentsFromRequests: (...a: unknown[]) => createFromRequestsMock(...a),
  getInvestmentFormConfig: (...a: unknown[]) => getFormConfigMock(...a),
  getInvestCompanies: (...a: unknown[]) => getCompaniesMock(...a),
  getProjectInvestments: (...a: unknown[]) => getProjectInvestmentsMock(...a),
  getInvestmentFundingConfig: (...a: unknown[]) => getFundingConfigMock(...a),
}))

let mainButtonHandler: (() => void) | null = null
const mainButtonMock = {
  onClick: vi.fn((fn: () => void) => {
    mainButtonHandler = fn
  }),
  offClick: vi.fn(),
  show: vi.fn(),
  hide: vi.fn(),
  showProgress: vi.fn(),
  hideProgress: vi.fn(),
  disable: vi.fn(),
  enable: vi.fn(),
  setText: vi.fn(),
}

const REQ = (id: number, extra: Record<string, unknown> = {}) => ({
  id,
  submitted_at: '2026-11-01T10:00:00+05:00',
  kind: 'expense',
  payment_type: 'Инвест. наличные',
  payment_purpose: 'Ремонт',
  description: `Описание ${id}`,
  amount: '1000.00',
  currency: 'UZS',
  status: 'approved',
  is_payed: false,
  ...extra,
})

function Where() {
  return <div data-testid="where">{useLocation().pathname}</div>
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/tg/investments/projects" element={<TgInvestmentsProjectsPage />} />
        <Route path="/tg/investments/projects/collect" element={<TgInvestmentsCollectPage />} />
        <Route path="*" element={<Where />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('TgInvestmentsCollectPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mainButtonHandler = null
    window.Telegram = { WebApp: { MainButton: mainButtonMock } } as unknown as typeof window.Telegram
    getFormConfigMock.mockResolvedValue({ uses_companies: false })
    getCompaniesMock.mockResolvedValue([])
    getProjectInvestmentsMock.mockResolvedValue([])
    getFundingConfigMock.mockResolvedValue({ is_enabled: true })
  })

  afterEach(() => {
    delete (window as { Telegram?: unknown }).Telegram
  })

  it('creates an investment from the selected requests of the chosen method', async () => {
    getFundingPoolMock.mockResolvedValue({
      cash: { requests: [REQ(11), REQ(12)], totals: [] },
      bank_transfer: { requests: [REQ(21, { payment_type: 'Инвест. перечисление' })], totals: [] },
      approval_chain_ok: true,
    })
    createFromRequestsMock.mockResolvedValue({ investments: [{ id: 501 }] })
    renderAt('/tg/investments/projects/collect')

    expect(await screen.findByLabelText('Заявка №11')).toBeTruthy()
    expect(screen.getByText(/\(2 заявки\)/)).toBeTruthy()

    fireEvent.click(screen.getByLabelText('Заявка №12'))
    await waitFor(() => expect(screen.getByText(/\(1 заявка\)/)).toBeTruthy())

    act(() => {
      mainButtonHandler?.()
    })

    await waitFor(() => expect(createFromRequestsMock).toHaveBeenCalledTimes(1))
    expect(createFromRequestsMock).toHaveBeenCalledWith({
      funding_method: 'cash',
      request_ids: [11],
      comment: '',
    })
    // После создания — возврат к списку вложений.
    expect(await screen.findByRole('heading', { name: 'Заявки на вложение' })).toBeTruthy()
  })

  it('shows the error and stays on the page when the backend rejects', async () => {
    getFundingPoolMock.mockResolvedValue({
      cash: { requests: [REQ(11)], totals: [] },
      bank_transfer: { requests: [], totals: [] },
      approval_chain_ok: false,
    })
    createFromRequestsMock.mockRejectedValue(new Error('Заявка уже собрана'))
    renderAt('/tg/investments/projects/collect')

    expect(await screen.findByText(/не настроено согласование/)).toBeTruthy()
    act(() => {
      mainButtonHandler?.()
    })
    expect(await screen.findByText('Заявка уже собрана')).toBeTruthy()
    expect(screen.queryByTestId('where')).toBeNull()
  })
})

describe('TgInvestmentsProjectsPage in investment funding mode', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    getFormConfigMock.mockResolvedValue({ uses_companies: false })
    getCompaniesMock.mockResolvedValue([])
    getProjectInvestmentsMock.mockResolvedValue([])
    getFundingPoolMock.mockReturnValue(new Promise(() => {}))
  })

  it('the add button leads to collecting by requests when the mode is on', async () => {
    getFundingConfigMock.mockResolvedValue({ is_enabled: true })
    renderAt('/tg/investments/projects')

    const btn = await screen.findByLabelText('Собрать вложение по заявкам')
    fireEvent.click(btn)
    expect(await screen.findByText('Вложение по заявкам')).toBeTruthy()
  })

  it('the add button opens the manual form when the mode is off', async () => {
    getFundingConfigMock.mockResolvedValue({ is_enabled: false })
    renderAt('/tg/investments/projects')

    await waitFor(() => expect(getFundingConfigMock).toHaveBeenCalled())
    fireEvent.click(await screen.findByLabelText('Создать заявку на вложение'))
    await waitFor(() => expect(screen.getByTestId('where').textContent).toBe('/tg/investments/projects/new'))
  })
})
