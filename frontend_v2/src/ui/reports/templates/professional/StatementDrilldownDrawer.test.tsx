import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { StatementLineItem } from '../../../../lib/reportsApi'

const getStatementLinesMock = vi.fn()
const downloadLinesXlsxMock = vi.fn()
const getReportRequestDetailMock = vi.fn()
vi.mock('../../../../lib/reportsApi', () => ({
  getStatementLines: (...args: unknown[]) => getStatementLinesMock(...args),
  downloadLinesXlsx: (...args: unknown[]) => downloadLinesXlsxMock(...args),
  getReportRequestDetail: (...args: unknown[]) => getReportRequestDetailMock(...args),
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
  // A block body: mockReset() returns the mock, and Vitest would run a returned function as a cleanup hook
  // after every test, calling getStatementLines() with no arguments.
  beforeEach(() => {
    getStatementLinesMock.mockReset()
    getReportRequestDetailMock.mockReset()
    getReportRequestDetailMock.mockReturnValue(new Promise(() => undefined))
  })

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
    // A click opens the card; the button opens the request itself.
    fireEvent.click(await screen.findByText('Таргет Instagram'))
    fireEvent.click(screen.getByRole('button', { name: 'Открыть заявку #4812' }))
    expect(onOpenRequest).toHaveBeenCalledWith(4812, null)
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
    const row = STATEMENT.rows[0]
    const huge = { ...REQUEST, row: { ...row, values: { ...row.values, '2026-08': '9007199254740992.00' } } }
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

  it('opens an amortized request on the instalment behind this cell', async () => {
    const onOpenRequest = vi.fn()
    getStatementLinesMock.mockResolvedValue(
      linesResponse(
        [item({ entry_id: 'operational:request:11:2', section: 'operational', source: 'request', request_id: 11, title: 'Выставка', channel: '', line_id: 'opex.11111111', line_label: 'Маркетинг', amount: '100000.00', amortization: { index: 2, count: 3 } })],
        '100000.00',
      ),
    )
    render(<StatementDrilldownDrawer request={REQUEST} units="m" onClose={vi.fn()} onOpenRequest={onOpenRequest} />)
    fireEvent.click(await screen.findByText('Выставка'))
    fireEvent.click(screen.getByRole('button', { name: 'Открыть заявку #11' }))
    expect(onOpenRequest).toHaveBeenCalledWith(11, 2)
  })

  const REQUEST_ITEMS = [
    item({ entry_id: 'operational:request:10:0', section: 'operational', source: 'request', request_id: 10, title: 'Аренда за август', channel: '', counterparty: 'ООО Офис', author: 'Азиз Рахимов', line_id: 'opex.22222222', line_label: 'Аренда', amount: '1200000.00' }),
    item({ entry_id: 'operational:request:12:0', section: 'operational', source: 'request', request_id: 12, title: 'Склад', channel: '', counterparty: ' ооо офис', line_id: 'opex.22222222', line_label: 'Аренда', amount: '300000.00' }),
    item({ entry_id: 'operational:request:13:0', section: 'operational', source: 'request', request_id: 13, title: 'Выставка', channel: '', counterparty: 'ИП Экспо', line_id: 'opex.11111111', line_label: 'Маркетинг', amount: '300000.00' }),
  ]

  it('shows who asked for the money and groups the cell by vendor', async () => {
    getStatementLinesMock.mockResolvedValue(linesResponse(REQUEST_ITEMS, '1800000.00'))
    render(<StatementDrilldownDrawer request={REQUEST} units="m" onClose={vi.fn()} onOpenRequest={vi.fn()} />)
    expect(await screen.findByText('Азиз Рахимов')).toBeInTheDocument()
    expect(screen.getByText('3 заявки')).toBeInTheDocument()
    fireEvent.click(screen.getByText('По поставщикам'))
    expect(await screen.findByText('2 операции')).toBeInTheDocument()
    expect(screen.getByText('ИП Экспо')).toBeInTheDocument()
  })

  it('loads the approvals of a request once when its card opens', async () => {
    getStatementLinesMock.mockResolvedValue(linesResponse(REQUEST_ITEMS.slice(0, 1), '1200000.00'))
    getReportRequestDetailMock.mockResolvedValue({
      id: 10,
      payment_type: 'Перечисление',
      attachments: [{ id: 1 }],
      approvals: [
        { id: 5, step: 1, step_type: 'approval', decision: 'approved', approver_username: 'director', decided_at: '2026-08-02T10:00:00+05:00' },
      ],
    })
    render(<StatementDrilldownDrawer request={REQUEST} units="m" onClose={vi.fn()} onOpenRequest={vi.fn()} />)
    const title = await screen.findByText('Аренда за август')
    fireEvent.click(title)
    expect(await screen.findByText(/director/)).toBeInTheDocument()
    expect(screen.getByText('Одобрено')).toBeInTheDocument()
    expect(screen.getByText('Оплата: Перечисление')).toBeInTheDocument()
    fireEvent.click(title)
    fireEvent.click(title)
    expect(getReportRequestDetailMock).toHaveBeenCalledTimes(1)
  })

  it('lists every section for a vendor panel', async () => {
    getStatementLinesMock.mockResolvedValue(linesResponse(REQUEST_ITEMS.slice(0, 2), '1500000.00'))
    const vendorRequest: DrillRequest = { ...REQUEST, row: null, vendor: 'ООО Офис', crumbs: ['Прибыли и убытки', 'Поставщики'] }
    render(<StatementDrilldownDrawer request={vendorRequest} units="m" onClose={vi.fn()} onOpenRequest={vi.fn()} />)
    expect(await screen.findByText('по всем разделам')).toBeInTheDocument()
    expect(getStatementLinesMock).toHaveBeenCalledWith(expect.objectContaining({ line: undefined, vendor: 'ООО Офис' }), expect.anything())
  })

  it('hides the composition until every operation is loaded', async () => {
    getStatementLinesMock.mockResolvedValue({ ...linesResponse(REQUEST_ITEMS, '1800000.00'), count: 250 })
    render(<StatementDrilldownDrawer request={REQUEST} units="m" onClose={vi.fn()} onOpenRequest={vi.fn()} />)
    expect(await screen.findByText('Показаны 3 из 250. Загрузите все, чтобы увидеть состав.')).toBeInTheDocument()
    expect(screen.queryByText('По поставщикам')).toBeNull()
  })

  it('draws the composition bar for a fully loaded cell', async () => {
    getStatementLinesMock.mockResolvedValue(linesResponse(REQUEST_ITEMS, '1800000.00'))
    render(<StatementDrilldownDrawer request={REQUEST} units="m" onClose={vi.fn()} onOpenRequest={vi.fn()} />)
    await screen.findByText('Аренда за август')
    expect(document.querySelectorAll('.rp-stack i')).toHaveLength(3)
  })
})
