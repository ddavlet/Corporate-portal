import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { Link, MemoryRouter, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { StructuredReportPayload, StructuredReportRow } from '../../../../lib/api'

const row = (
  id: string,
  section: StructuredReportRow['section'],
  category: string,
  purpose: string,
  vendor = '',
): StructuredReportRow => ({
  id,
  date: '2026-08-05T00:00:00',
  amount: '100.00',
  direction: section === 'revenue' ? 'revenue' : 'expense',
  section,
  category,
  purpose,
  description: '',
  channel: '',
  raw: vendor ? { vendor } : {},
})

const PAYLOAD = {
  report: 'pnl',
  metadata: {},
  totals: { revenue: '100', expense: '200', net: '-100' },
  monthly: [],
  rows: [
    row('1', 'revenue', 'Продажи', 'Поступление от клиента'),
    row('2', 'operational', 'Аренда', 'Аренда офиса за август', 'ZARKENT POLIMER INVEST'),
    row('3', 'other', 'Налоги', 'Налог НДС за август'),
  ],
  revenue: [],
  operational_expenses: [],
  other_expenses: [],
} as unknown as StructuredReportPayload

const getStructuredPnlReportMock = vi.fn()
const getStructuredCashflowReportMock = vi.fn()
vi.mock('../../../../lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../../lib/api')>()
  return {
    ...actual,
    // Read lazily: this factory is hoisted above the mocks it calls.
    getStructuredPnlReport: () => getStructuredPnlReportMock(),
    getStructuredCashflowReport: () => getStructuredCashflowReportMock(),
  }
})

import { ClassicReportTemplate } from './ClassicReportTemplate'

const SEARCH_BOX = 'Поиск по назначению/каналу/описанию/поставщику'

function Location() {
  return <output data-testid="location">{useLocation().search}</output>
}

function tree(url: string, report: 'pnl' | 'cashflow', rulesVersion: number) {
  return (
    <MemoryRouter initialEntries={[url]}>
      <ClassicReportTemplate report={report} onOpenRules={null} rulesVersion={rulesVersion} />
      <Location />
    </MemoryRouter>
  )
}

function renderAt(url: string, report: 'pnl' | 'cashflow' = 'pnl') {
  const view = render(tree(url, report, 0))
  return { ...view, rerenderRules: (rulesVersion: number) => view.rerender(tree(url, report, rulesVersion)) }
}

describe('ClassicReportTemplate', () => {
  beforeEach(() => {
    // The page scrolls the operations card into view; jsdom has no layout, so the call is a no-op here.
    Object.defineProperty(Element.prototype, 'scrollIntoView', { value: vi.fn(), configurable: true })
    getStructuredPnlReportMock.mockReset().mockResolvedValue(PAYLOAD)
    getStructuredCashflowReportMock.mockReset().mockResolvedValue({ ...PAYLOAD, report: 'cashflow' })
  })

  it('opens only operational expenses from «Итого операционные расходы»', async () => {
    renderAt('/reports/classic/pnl')
    fireEvent.click(await screen.findByText('Итого операционные расходы'))
    expect(await screen.findByText('Фильтр: Операционные расходы')).toBeInTheDocument()
    expect(screen.getByText('Аренда офиса за август')).toBeInTheDocument()
    expect(screen.queryByText('Налог НДС за август')).toBeNull()
    expect(screen.queryByText('Поступление от клиента')).toBeNull()
  })

  it('shows the vendor of each operation, finds operations by it and keeps the search in the link', async () => {
    renderAt('/reports/classic/pnl')
    expect(await screen.findByText('ZARKENT POLIMER INVEST')).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: /Поставщик/ })).toBeInTheDocument()
    fireEvent.change(screen.getByPlaceholderText(SEARCH_BOX), { target: { value: 'zarkent' } })
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('q=zarkent'))
    expect(screen.getByText('Аренда офиса за август')).toBeInTheDocument()
    expect(screen.queryByText('Налог НДС за август')).toBeNull()
  })

  it('keeps what is typed and writes the search to the link after a pause', async () => {
    renderAt('/reports/classic/pnl')
    await screen.findByText('ZARKENT POLIMER INVEST')
    const box = screen.getByPlaceholderText(SEARCH_BOX)
    fireEvent.change(box, { target: { value: 'zar' } })
    fireEvent.change(box, { target: { value: 'zark' } })
    // The router applies a new link in a transition, which would undo keystrokes; the box does not wait for it.
    expect(box).toHaveValue('zark')
    expect(screen.getByTestId('location').textContent).toBe('')
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('q=zark'))
  })

  it('follows a search that a new link brings', async () => {
    render(
      <MemoryRouter initialEntries={['/reports/classic/pnl?q=zarkent']}>
        <ClassicReportTemplate report="pnl" onOpenRules={null} rulesVersion={0} />
        <Link to="?q=налог">налог</Link>
      </MemoryRouter>,
    )
    expect(await screen.findByText('Аренда офиса за август')).toBeInTheDocument()
    const box = screen.getByPlaceholderText(SEARCH_BOX)
    expect(box).toHaveValue('zarkent')
    fireEvent.click(screen.getByRole('link', { name: 'налог' }))
    await waitFor(() => expect(box).toHaveValue('налог'))
    expect(screen.getByText('Налог НДС за август')).toBeInTheDocument()
    expect(screen.queryByText('Аренда офиса за август')).toBeNull()
  })

  it('asks only for the report it shows', async () => {
    renderAt('/reports/classic/cashflow', 'cashflow')
    expect(await screen.findByText('Cashflow: сводный отчет')).toBeInTheDocument()
    expect(getStructuredCashflowReportMock).toHaveBeenCalledTimes(1)
    expect(getStructuredPnlReportMock).not.toHaveBeenCalled()
  })

  it('restores the search from the link', async () => {
    renderAt('/reports/classic/pnl?q=zarkent')
    expect(await screen.findByText('Аренда офиса за август')).toBeInTheDocument()
    expect(screen.queryByText('Налог НДС за август')).toBeNull()
  })

  it('restores the year from the link', async () => {
    getStructuredPnlReportMock.mockResolvedValue({
      ...PAYLOAD,
      revenue: [{ id: 1, date: '2025-03-10T00:00:00', amount: '100.00', category: 'Продажи' }],
    })
    renderAt('/reports/classic/pnl?y=2025')
    expect(await screen.findByRole('radio', { name: '2025' })).toBeChecked()
  })

  it('loads the report again after its rules are saved', async () => {
    const { rerenderRules } = renderAt('/reports/classic/pnl')
    await screen.findByText('PnL: сводный отчет')
    rerenderRules(1)
    await waitFor(() => expect(getStructuredPnlReportMock).toHaveBeenCalledTimes(2))
  })
})
