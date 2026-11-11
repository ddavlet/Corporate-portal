import { render, screen, waitFor } from '@testing-library/react'
import { message } from 'antd'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const getProjectInvestmentsMock = vi.fn()
const getInvestReturnsMock = vi.fn()

vi.mock('../lib/api', () => ({
  DEFAULT_INVESTMENT_FORM_CONFIG: { allowed_return_types: [], return_type_choices: [] },
  getInvestmentFormConfig: () => Promise.resolve({ allowed_return_types: [], return_type_choices: [] }),
  getInvestNotificationConfig: () => Promise.resolve(null),
  getInvestPayoutSchedule: () => Promise.resolve([]),
  getInvestPayoutScheduleShareLinks: () => Promise.resolve([]),
  getInvestReturns: () => getInvestReturnsMock(),
  getProjectInvestments: () => getProjectInvestmentsMock(),
}))

// The tabs and the card have their own tests; here only the deep link matters.
vi.mock('./investments/InvestmentsTab', () => ({ InvestmentsTab: () => <div>Вкладка вложений</div> }))
vi.mock('./investments/ReturnsTab', () => ({ ReturnsTab: () => <div>Вкладка выплат</div> }))
vi.mock('./investments/ScheduleTab', () => ({ ScheduleTab: () => null }))
vi.mock('./investments/InvestmentRecordDetailModal', () => ({
  InvestmentRecordDetailModal: ({ open, kind, record }: { open: boolean; kind: string | null; record: { id: number } | null }) =>
    open && record ? <div role="dialog">{`Карточка ${kind} #${record.id}`}</div> : null,
}))

import { InvestmentsPage } from './InvestmentsPage'

function LocationProbe() {
  const location = useLocation()
  return <div data-testid="location">{location.search}</div>
}

function renderPage(url: string) {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <InvestmentsPage />
      <LocationProbe />
    </MemoryRouter>,
  )
}

describe('InvestmentsPage deep link ?open=', () => {
  beforeEach(() => {
    getProjectInvestmentsMock.mockResolvedValue([{ id: 8 }])
    getInvestReturnsMock.mockResolvedValue([{ id: 5 }])
  })

  it('opens the linked return card', async () => {
    const warning = vi.spyOn(message, 'warning')
    renderPage('/investments?tab=returns&open=5')
    expect(await screen.findByRole('dialog')).toHaveTextContent('Карточка return #5')
    expect(warning).not.toHaveBeenCalled()
    expect(screen.getByTestId('location')).toHaveTextContent('open=5')
  })

  it('warns and drops ?open= when the record is not in the loaded list', async () => {
    const warning = vi.spyOn(message, 'warning')
    renderPage('/investments?tab=returns&open=99')
    await waitFor(() => expect(warning).toHaveBeenCalledWith('Запись #99 не найдена или нет доступа'))
    expect(warning).toHaveBeenCalledTimes(1)
    await waitFor(() => expect(screen.getByTestId('location')).not.toHaveTextContent('open='))
    expect(screen.getByTestId('location')).toHaveTextContent('tab=returns')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('warns when the lists could not be loaded (no access to the module)', async () => {
    getInvestReturnsMock.mockRejectedValue(Object.assign(new Error('Нет доступа'), { status: 403 }))
    const warning = vi.spyOn(message, 'warning')
    renderPage('/investments?tab=returns&open=5')
    await waitFor(() => expect(warning).toHaveBeenCalledWith('Запись #5 не найдена или нет доступа'))
    await waitFor(() => expect(screen.getByTestId('location')).not.toHaveTextContent('open='))
  })

  it('stays quiet without ?open=', async () => {
    const warning = vi.spyOn(message, 'warning')
    renderPage('/investments?tab=returns')
    expect(await screen.findByText('Вкладка выплат')).toBeInTheDocument()
    await waitFor(() => expect(getInvestReturnsMock).toHaveBeenCalled())
    expect(warning).not.toHaveBeenCalled()
  })
})

describe('InvestmentsPage without companies inside the tenant', () => {
  beforeEach(() => {
    getProjectInvestmentsMock.mockResolvedValue([])
    getInvestReturnsMock.mockResolvedValue([])
  })

  it('shows no "Компании" tab and no company filter', async () => {
    renderPage('/investments')
    expect(await screen.findByRole('tab', { name: /Заявки на вложение/ })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /Расписание/ })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /Выплаты/ })).toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: /Компании/ })).not.toBeInTheDocument()
    expect(screen.queryByText('Все компании')).not.toBeInTheDocument()
  })

  it('opens the first tab even when an old link asks for ?tab=companies', async () => {
    renderPage('/investments?tab=companies')
    expect(await screen.findByText('Вкладка вложений')).toBeInTheDocument()
  })
})
