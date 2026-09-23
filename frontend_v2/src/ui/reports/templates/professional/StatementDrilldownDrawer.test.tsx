import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { StatementLineItem } from '../../../../lib/reportsApi'

const getStatementLinesMock = vi.fn()
const downloadLinesXlsxMock = vi.fn()
vi.mock('../../../../lib/reportsApi', () => ({
  getStatementLines: (...args: unknown[]) => getStatementLinesMock(...args),
  downloadLinesXlsx: (...args: unknown[]) => downloadLinesXlsxMock(...args),
}))

const saveFileMock = vi.fn()
vi.mock('../../../../lib/saveFile', () => ({ saveFile: (...args: unknown[]) => saveFileMock(...args) }))
vi.mock('../../../../lib/apiNotify', () => ({ notifyApiError: vi.fn(), notifyApiSuccess: vi.fn(), notifyNetworkError: vi.fn() }))

import { StatementDrilldownDrawer, type DrillRequest } from './StatementDrilldownDrawer'
import { STATEMENT } from './testStatement'

const item = (over: Partial<StatementLineItem>): StatementLineItem => ({
  entry_id: 'revenue:bank:2:0',
  date: '2026-08-05',
  amount: '1500000.00',
  section: 'revenue',
  source: 'bank',
  category: 'Поступление в банк',
  title: 'CLICK: перечисление',
  counterparty: '',
  request_id: null,
  channel: 'CLICK',
  line_id: 'rev.bank',
  line_label: 'Банк',
  amortization: null,
  ...over,
})

const REQUEST: DrillRequest = {
  template: 'professional',
  report: 'pnl',
  row: STATEMENT.rows[0],
  column: STATEMENT.columns[0],
  crumbs: ['Прибыли и убытки'],
}

function linesResponse(items: StatementLineItem[], total: string) {
  return { line: 'rev', total, count: items.length, page: 1, page_size: 50, items }
}

describe('StatementDrilldownDrawer', () => {
  beforeEach(() => getStatementLinesMock.mockReset())

  it('reconciles the list with the cell', async () => {
    getStatementLinesMock.mockResolvedValue(
      linesResponse([item({}), item({ entry_id: 'revenue:cash:3:0', source: 'cash', amount: '300000.00', title: 'Продажа', line_id: 'rev.cash.a1b2c3d4', line_label: 'Продажа' })], '1800000.00'),
    )
    render(<StatementDrilldownDrawer request={REQUEST} units="m" onClose={vi.fn()} onOpenRequest={vi.fn()} />)
    expect(await screen.findByText('совпадает')).toBeInTheDocument()
    const stats = (document.querySelector('.rp-drill-stats')?.textContent ?? '').replace(/[  ]/g, ' ')
    expect(stats).toContain('Сумма, сум1 800 000')
    expect(stats).toContain('Операций2')
    expect(getStatementLinesMock).toHaveBeenCalledWith(
      expect.objectContaining({ template: 'professional', report: 'pnl', line: 'rev', from: '2026-08-01', to: '2026-08-31', page: 1 }),
      expect.anything(),
    )
  })

  it('flags a list that does not add up', async () => {
    getStatementLinesMock.mockResolvedValue(linesResponse([item({})], '1500000.00'))
    render(<StatementDrilldownDrawer request={REQUEST} units="m" onClose={vi.fn()} onOpenRequest={vi.fn()} />)
    expect(await screen.findByText('расхождение')).toBeInTheDocument()
  })

  it('does not claim a match while searching', async () => {
    getStatementLinesMock.mockResolvedValue(linesResponse([item({})], '1800000.00'))
    render(<StatementDrilldownDrawer request={REQUEST} units="m" onClose={vi.fn()} onOpenRequest={vi.fn()} />)
    await screen.findByText('совпадает')
    getStatementLinesMock.mockResolvedValue(linesResponse([item({})], '1500000.00'))
    const input = screen.getByLabelText('Поиск по операциям ячейки')
    fireEvent.change(input, { target: { value: 'click' } })
    fireEvent.keyDown(input, { key: 'Enter', code: 'Enter', keyCode: 13 })
    await waitFor(() => expect(getStatementLinesMock).toHaveBeenLastCalledWith(expect.objectContaining({ q: 'click', page: 1 }), expect.anything()))
    expect(await screen.findByText('по всем операциям')).toBeInTheDocument()
    expect(screen.queryByText('совпадает')).toBeNull()
  })

  it('opens a request from the list', async () => {
    const onOpenRequest = vi.fn()
    getStatementLinesMock.mockResolvedValue(
      linesResponse([item({ entry_id: 'operational:request:4812:0', section: 'operational', source: 'request', request_id: 4812, title: 'Таргет Instagram', channel: '', line_id: 'opex.11111111', line_label: 'Маркетинг', amount: '1800000.00' })], '1800000.00'),
    )
    render(<StatementDrilldownDrawer request={REQUEST} units="m" onClose={vi.fn()} onOpenRequest={onOpenRequest} />)
    fireEvent.click(await screen.findByText('Таргет Instagram'))
    expect(onOpenRequest).toHaveBeenCalledWith(4812)
  })

  it('exports the cell operations to Excel with the current search', async () => {
    getStatementLinesMock.mockResolvedValue(linesResponse([item({})], '1800000.00'))
    downloadLinesXlsxMock.mockResolvedValue({ blob: new Blob(['x']), filename: 'PnL_operations.xlsx' })
    render(<StatementDrilldownDrawer request={REQUEST} units="m" onClose={vi.fn()} onOpenRequest={vi.fn()} />)
    await screen.findByText('совпадает')
    const input = screen.getByLabelText('Поиск по операциям ячейки')
    fireEvent.change(input, { target: { value: 'click' } })
    fireEvent.keyDown(input, { key: 'Enter', code: 'Enter', keyCode: 13 })
    await screen.findByText('по всем операциям')
    fireEvent.click(screen.getByRole('button', { name: /Excel/ }))
    await waitFor(() => expect(saveFileMock).toHaveBeenCalledWith({ blob: expect.any(Blob), filename: 'PnL_operations.xlsx' }))
    expect(downloadLinesXlsxMock).toHaveBeenCalledWith({
      template: 'professional',
      report: 'pnl',
      line: 'rev',
      from: '2026-08-01',
      to: '2026-08-31',
      q: 'click',
    })
  })

  it('explains a connection failure in Russian', async () => {
    getStatementLinesMock.mockRejectedValue(new TypeError('Failed to fetch'))
    render(<StatementDrilldownDrawer request={REQUEST} units="m" onClose={vi.fn()} onOpenRequest={vi.fn()} />)
    expect(await screen.findByText('Нет связи с сервером. Проверьте интернет и повторите.')).toBeInTheDocument()
  })

  it('reconciles exactly for very large sums', async () => {
    getStatementLinesMock.mockResolvedValue(linesResponse([item({})], '9007199254740993.00'))
    const huge = { ...REQUEST, row: { ...REQUEST.row, values: { ...REQUEST.row.values, '2026-08': '9007199254740992.00' } } }
    render(<StatementDrilldownDrawer request={huge} units="m" onClose={vi.fn()} onOpenRequest={vi.fn()} />)
    expect(await screen.findByText('расхождение')).toBeInTheDocument()
  })

  it('offers the link while the panel is open', async () => {
    getStatementLinesMock.mockResolvedValue(linesResponse([item({})], '1800000.00'))
    const onCopyLink = vi.fn()
    render(
      <StatementDrilldownDrawer request={REQUEST} units="m" onClose={vi.fn()} onOpenRequest={vi.fn()} onCopyLink={onCopyLink} />,
    )
    await screen.findByText('совпадает')
    fireEvent.click(screen.getByRole('button', { name: /Ссылка/ }))
    expect(onCopyLink).toHaveBeenCalledTimes(1)
  })
})
