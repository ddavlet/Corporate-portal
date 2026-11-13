import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { message } from 'antd'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createMobileHeaderStore, MobileShellContext, type MobileHeaderStore } from '../mobileShell'
import { InvestmentsMobilePage } from './InvestmentsMobilePage'

const api = vi.hoisted(() => ({
  getInvestReturns: vi.fn(),
  getProjectInvestments: vi.fn(),
  getInvestmentFundingConfig: vi.fn(),
}))

vi.mock('../../lib/api', () => ({
  getInvestReturns: (...a: unknown[]) => api.getInvestReturns(...a),
  getProjectInvestments: (...a: unknown[]) => api.getProjectInvestments(...a),
  getInvestmentFundingConfig: (...a: unknown[]) => api.getInvestmentFundingConfig(...a),
}))

const access = vi.hoisted(() => ({
  value: { loading: false, hasAccess: (_key: string): boolean => true } as {
    loading: boolean
    hasAccess: (key: string) => boolean
  },
}))

vi.mock('../moduleAccess', () => ({
  useModuleAccess: () => access.value,
}))

// The card itself is covered by InvestmentRecordDetailModal.test; here — which record it gets and how it closes.
vi.mock('./InvestmentRecordDetailModal', () => ({
  InvestmentRecordDetailModal: (props: {
    open: boolean
    kind: string | null
    record: { id: number } | null
    variant?: string
    descriptionsLayout?: string
    allowResend?: boolean
    onCancel: () => void
  }) =>
    props.open ? (
      <div data-testid="record-card">
        {`${props.kind} #${props.record?.id} ${props.variant} ${props.descriptionsLayout} resend:${String(props.allowResend)}`}
        <button type="button" onClick={props.onCancel}>
          Закрыть карточку
        </button>
      </div>
    ) : null,
}))

function LocationProbe() {
  const location = useLocation()
  return <div data-testid="location">{`${location.pathname}${location.search}`}</div>
}

function renderPage(url = '/investments', store: MobileHeaderStore | null = null) {
  return render(
    <MobileShellContext.Provider
      value={{ userId: 1, userIdStatus: 'ready', openCompanySwitcher: () => undefined, headerStore: store }}
    >
      <MemoryRouter initialEntries={[url]}>
        <Routes>
          <Route path="/investments" element={<InvestmentsMobilePage />} />
          <Route path="/investments/returns/new" element={<div>Форма выплаты</div>} />
          <Route path="/investments/collect" element={<div>Мастер сбора</div>} />
          <Route path="/investments/new" element={<div>Форма вложения</div>} />
        </Routes>
        <LocationProbe />
      </MemoryRouter>
    </MobileShellContext.Provider>,
  )
}

const currentPath = () => screen.getByTestId('location').textContent

/** Lets the funding-mode request settle. */
async function settle() {
  await waitFor(() => expect(api.getInvestmentFundingConfig).toHaveBeenCalled())
  await act(async () => {
    await Promise.resolve()
  })
}

let warningSpy: ReturnType<typeof vi.spyOn>

beforeEach(() => {
  access.value = { loading: false, hasAccess: () => true }
  api.getInvestReturns.mockReset().mockResolvedValue([{ id: 5, date: '2026-11-10' }])
  api.getProjectInvestments.mockReset().mockResolvedValue([{ id: 7, date: '2026-11-10' }])
  api.getInvestmentFundingConfig.mockReset().mockResolvedValue({ is_enabled: false })
  warningSpy = vi.spyOn(message, 'warning').mockImplementation(() => undefined as never)
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('InvestmentsMobilePage', () => {
  it('sets the header and shows the payout action without tables, tabs or filters', async () => {
    const store = createMobileHeaderStore()
    const { container } = renderPage('/investments', store)
    await settle()

    expect(store.get()).toMatchObject({ title: 'Инвестиции' })
    expect(store.get()?.back).toBeUndefined()
    expect(screen.getByRole('button', { name: /Создать выплату/ })).toBeInTheDocument()
    expect(container.querySelector('.ant-table')).toBeNull()
    expect(container.querySelector('.ant-tabs')).toBeNull()
    expect(container.querySelector('.ant-picker-range')).toBeNull()
    expect(container.querySelector('.ant-select')).toBeNull()
    expect(api.getInvestReturns).not.toHaveBeenCalled()
    expect(api.getProjectInvestments).not.toHaveBeenCalled()
    // No «на компьютере» hints: what a phone cannot do is simply not offered.
    expect(screen.queryByText(/компьютер/)).toBeNull()
  })

  it('offers «Собрать из заявок» and not «Подать заявку на вложение» in the investment mode', async () => {
    api.getInvestmentFundingConfig.mockResolvedValue({ is_enabled: true })
    renderPage()
    expect(await screen.findByRole('button', { name: /Собрать из заявок/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Подать заявку на вложение/ })).toBeNull()
    expect(screen.getByRole('button', { name: /Создать выплату/ })).toBeInTheDocument()
  })

  it('offers «Подать заявку на вложение» and not «Собрать из заявок» without the investment mode', async () => {
    renderPage()
    expect(await screen.findByRole('button', { name: /Подать заявку на вложение/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Собрать из заявок/ })).toBeNull()
    expect(screen.getByRole('button', { name: /Создать выплату/ })).toBeInTheDocument()
  })

  it('offers «Подать заявку на вложение» when the funding config does not load, as the desktop does', async () => {
    api.getInvestmentFundingConfig.mockRejectedValue(new Error('403'))
    renderPage()
    expect(await screen.findByRole('button', { name: /Подать заявку на вложение/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Собрать из заявок/ })).toBeNull()
    expect(screen.getByRole('button', { name: /Создать выплату/ })).toBeInTheDocument()
  })

  it('shows neither mode action until the funding config answers', () => {
    api.getInvestmentFundingConfig.mockReturnValue(new Promise(() => undefined))
    renderPage()
    expect(screen.getByRole('button', { name: /Создать выплату/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Собрать из заявок/ })).toBeNull()
    expect(screen.queryByRole('button', { name: /Подать заявку на вложение/ })).toBeNull()
  })

  it('opens the payout form and the collect wizard', async () => {
    api.getInvestmentFundingConfig.mockResolvedValue({ is_enabled: true })
    const first = renderPage()
    fireEvent.click(screen.getByRole('button', { name: /Создать выплату/ }))
    expect(currentPath()).toBe('/investments/returns/new')
    first.unmount()

    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /Собрать из заявок/ }))
    expect(currentPath()).toBe('/investments/collect')
  })

  it('opens the investment form without the investment mode', async () => {
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /Подать заявку на вложение/ }))
    expect(currentPath()).toBe('/investments/new')
    expect(screen.getByText('Форма вложения')).toBeInTheDocument()
  })

  it('shows an empty state without access to the module', async () => {
    access.value = { loading: false, hasAccess: () => false }
    renderPage()
    expect(screen.getByText('Раздел недоступен')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Создать выплату/ })).toBeNull()
    expect(api.getInvestmentFundingConfig).not.toHaveBeenCalled()
  })
})

describe('InvestmentsMobilePage: a link from a notification', () => {
  it('opens the payout card in the vertical layout and drops «open» on close', async () => {
    renderPage('/investments?tab=returns&open=5')

    expect(screen.getByTestId('mobile-state-loading')).toBeInTheDocument()
    expect((await screen.findByTestId('record-card')).textContent).toContain('return #5 portal vertical')
    // No resending approvals on a phone: the card gets allowResend={false}.
    expect(screen.getByTestId('record-card').textContent).toContain('resend:false')
    expect(api.getProjectInvestments).not.toHaveBeenCalled()
    expect(warningSpy).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: 'Закрыть карточку' }))
    expect(screen.queryByTestId('record-card')).toBeNull()
    expect(currentPath()).toBe('/investments?tab=returns')
  })

  it('opens the investment card', async () => {
    renderPage('/investments?tab=investments&open=7')
    expect((await screen.findByTestId('record-card')).textContent).toContain('project #7')
    expect(api.getInvestReturns).not.toHaveBeenCalled()
  })

  it('reports a record that is not there and drops «open»', async () => {
    renderPage('/investments?tab=returns&open=999')

    await waitFor(() => expect(warningSpy).toHaveBeenCalledWith('Запись #999 не найдена или нет доступа'))
    await waitFor(() => expect(currentPath()).toBe('/investments?tab=returns'))
    expect(screen.queryByTestId('record-card')).toBeNull()
    expect(screen.getByRole('button', { name: /Создать выплату/ })).toBeInTheDocument()
  })

  it('reports a failed load the same way', async () => {
    api.getInvestReturns.mockRejectedValue(new Error('Нет доступа'))
    renderPage('/investments?tab=returns&open=5')
    await waitFor(() => expect(warningSpy).toHaveBeenCalledWith('Запись #5 не найдена или нет доступа'))
    await waitFor(() => expect(currentPath()).toBe('/investments?tab=returns'))
  })

  it('ignores the schedule link and loads nothing', async () => {
    renderPage('/investments?tab=schedule&schedule=3')
    await settle()

    expect(api.getInvestReturns).not.toHaveBeenCalled()
    expect(api.getProjectInvestments).not.toHaveBeenCalled()
    expect(warningSpy).not.toHaveBeenCalled()
    expect(currentPath()).toBe('/investments?tab=schedule&schedule=3')
  })
})
