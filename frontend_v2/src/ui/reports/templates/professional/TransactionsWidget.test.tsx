import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const getStatementLinesMock = vi.fn()
vi.mock('../../../../lib/reportsApi', () => ({
  getStatementLines: (...args: unknown[]) => getStatementLinesMock(...args),
}))

import { TransactionsWidget } from './TransactionsWidget'
import { STATEMENT } from './testStatement'

const LINES = {
  line: '',
  total: '1700000.00',
  count: 2,
  page: 1,
  page_size: 50,
  items: [
    { entry_id: 'revenue:bank:2:0', date: '2026-08-05', amount: '1500000.00', section: 'revenue', source: 'bank', category: 'Поступление в банк', title: 'CLICK: перечисление', counterparty: '', request_id: null, channel: 'CLICK', line_id: 'rev.bank', line_label: 'Банк', amortization: null },
    { entry_id: 'operational:request:10:0', date: '2026-08-01', amount: '200000.00', section: 'operational', source: 'request', category: 'Аренда', title: 'Аренда за август', counterparty: 'ООО Офис', request_id: 10, channel: '', line_id: 'opex.22222222', line_label: 'Аренда', amortization: null },
  ],
}

describe('TransactionsWidget', () => {
  // A block body: mockReset() returns the mock, and Vitest would run a returned function as a cleanup hook
  // after every test, calling getStatementLines() with no arguments.
  beforeEach(() => {
    getStatementLinesMock.mockReset()
  })

  it('starts with clean filters when the report or period changes', async () => {
    getStatementLinesMock.mockResolvedValue(LINES)
    const { rerender } = render(
      <TransactionsWidget template="professional" report="pnl" from="2026-08-01" to="2026-08-31" rows={STATEMENT.rows} onOpenRequest={vi.fn()} />,
    )
    await screen.findByText('Аренда за август')
    fireEvent.mouseDown(screen.getByText('Все разделы'))
    fireEvent.click(await screen.findByTitle('Операционные расходы'))
    await waitFor(() =>
      expect(getStatementLinesMock).toHaveBeenLastCalledWith(expect.objectContaining({ line: 'opex' }), expect.anything()),
    )
    rerender(
      <TransactionsWidget template="professional" report="cashflow" from="2026-01-01" to="2026-09-23" rows={STATEMENT.rows} onOpenRequest={vi.fn()} />,
    )
    await waitFor(() =>
      expect(getStatementLinesMock).toHaveBeenLastCalledWith(
        expect.objectContaining({ report: 'cashflow', line: undefined, page: 1 }),
        expect.anything(),
      ),
    )
  })

  it('lists every section for the period and splits money in and out', async () => {
    getStatementLinesMock.mockResolvedValue({
      line: '',
      total: '1700000.00',
      count: 2,
      page: 1,
      page_size: 50,
      items: [
        { entry_id: 'revenue:bank:2:0', date: '2026-08-05', amount: '1500000.00', section: 'revenue', source: 'bank', category: 'Поступление в банк', title: 'CLICK: перечисление', counterparty: '', request_id: null, channel: 'CLICK', line_id: 'rev.bank', line_label: 'Банк', amortization: null },
        { entry_id: 'operational:request:10:0', date: '2026-08-01', amount: '200000.00', section: 'operational', source: 'request', category: 'Аренда', title: 'Аренда за август', counterparty: 'ООО Офис', request_id: 10, channel: '', line_id: 'opex.22222222', line_label: 'Аренда', amortization: null },
      ],
    })
    render(<TransactionsWidget template="professional" report="pnl" from="2026-08-01" to="2026-08-31" rows={STATEMENT.rows} onOpenRequest={vi.fn()} />)
    await waitFor(() =>
      expect(getStatementLinesMock).toHaveBeenCalledWith(
        expect.objectContaining({ line: undefined, source: undefined, from: '2026-08-01', to: '2026-08-31', page: 1 }),
        expect.anything(),
      ),
    )
    expect(await screen.findByText('Аренда за август')).toBeInTheDocument()
    expect(screen.getByText('Операционные расходы')).toBeInTheDocument()
    expect(screen.getByText('Заявка #10')).toBeInTheDocument()
  })
})
