import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const getStatementMock = vi.fn()
const downloadStatementXlsxMock = vi.fn()
const getStatementVendorsMock = vi.fn()
vi.mock('../../../../lib/reportsApi', () => ({
  getStatement: (...args: unknown[]) => getStatementMock(...args),
  // Pending: the «Операции» view only needs to mount.
  getStatementLines: () => new Promise(() => undefined),
  getStatementVendors: (...args: unknown[]) => getStatementVendorsMock(...args),
  getReportRequestDetail: vi.fn(),
  downloadStatementXlsx: (...args: unknown[]) => downloadStatementXlsxMock(...args),
  downloadLinesXlsx: vi.fn(),
}))

const saveFileMock = vi.fn()
vi.mock('../../../../lib/saveFile', () => ({ saveFile: (...args: unknown[]) => saveFileMock(...args) }))

const notifyApiErrorMock = vi.fn()
const notifyApiSuccessMock = vi.fn()
vi.mock('../../../../lib/apiNotify', () => ({
  notifyApiError: (...args: unknown[]) => notifyApiErrorMock(...args),
  notifyApiSuccess: (...args: unknown[]) => notifyApiSuccessMock(...args),
  notifyNetworkError: vi.fn(),
  setAntdMessageApi: vi.fn(),
}))

const useTenantAdminMock = vi.fn()
vi.mock('../../../../lib/useTenantAdmin', () => ({ useTenantAdmin: () => useTenantAdminMock() }))

vi.mock('../../../../lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../../lib/api')>()
  return {
    ...actual,
    getUserPreferences: vi.fn().mockResolvedValue({}),
    setUserPreference: vi.fn().mockResolvedValue(undefined),
  }
})

import { ApiError } from '../../../../lib/api'
import { NETWORK_ERROR_MESSAGE } from '../../../../lib/reportErrors'
import { ProfessionalReportTemplate } from './ProfessionalReportTemplate'
import { STATEMENT } from './testStatement'
import type { ReportTemplateProps } from '../types'

function template(props: Partial<ReportTemplateProps> = {}) {
  return <ProfessionalReportTemplate report="pnl" onOpenRules={null} rulesVersion={0} {...props} />
}

function renderAt(url: string, props: Partial<ReportTemplateProps> = {}) {
  const view = render(<MemoryRouter initialEntries={[url]}>{template(props)}</MemoryRouter>)
  return {
    ...view,
    rerenderWith: (next: Partial<ReportTemplateProps>) =>
      view.rerender(<MemoryRouter initialEntries={[url]}>{template({ ...props, ...next })}</MemoryRouter>),
  }
}

describe('ProfessionalReportTemplate', () => {
  beforeEach(() => {
    getStatementMock.mockReset()
    downloadStatementXlsxMock.mockReset()
    getStatementVendorsMock.mockReset()
    getStatementVendorsMock.mockReturnValue(new Promise(() => undefined))
    useTenantAdminMock.mockReturnValue({ isAdmin: false, loading: false })
  })

  it('requests the statement for the period in the link', async () => {
    getStatementMock.mockResolvedValue(STATEMENT)
    renderAt('/reports?p=month&m=2026-08')
    await waitFor(() =>
      expect(getStatementMock).toHaveBeenCalledWith(
        expect.objectContaining({ template: 'professional', report: 'pnl', period: 'month', month: '2026-08' }),
        expect.anything(),
      ),
    )
    expect(await screen.findByText('Отчёт о прибылях и убытках')).toBeInTheDocument()
  })

  it('explains that the report is not configured and opens its rules', async () => {
    useTenantAdminMock.mockReturnValue({ isAdmin: true, loading: false })
    getStatementMock.mockRejectedValue(new ApiError(503, 'No tenant_report_settings for tenant_id=1'))
    const onOpenRules = vi.fn()
    renderAt('/reports', { onOpenRules })
    expect(await screen.findByText('Отчёт не настроен')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Настроить отчёт' }))
    expect(onOpenRules).toHaveBeenCalledTimes(1)
  })

  it('shows the data warning to admins only', async () => {
    getStatementMock.mockResolvedValue(STATEMENT)
    useTenantAdminMock.mockReturnValue({ isAdmin: true, loading: false })
    const { unmount } = renderAt('/reports')
    expect(await screen.findByText(/Не попали в отчёт оплаченные заявки/)).toBeInTheDocument()
    unmount()
    useTenantAdminMock.mockReturnValue({ isAdmin: false, loading: false })
    renderAt('/reports')
    await screen.findByText('Отчёт о прибылях и убытках')
    expect(screen.queryByText(/Не попали в отчёт оплаченные заявки/)).toBeNull()
  })

  it('copies the address of the page', async () => {
    getStatementMock.mockResolvedValue(STATEMENT)
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    renderAt('/reports?p=month&m=2026-08')
    await screen.findByText('Отчёт о прибылях и убытках')
    fireEvent.click(screen.getByRole('button', { name: /Ссылка/ }))
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(window.location.href))
  })

  it('does not keep the previous report on screen when the next one cannot be built', async () => {
    getStatementMock
      .mockResolvedValueOnce(STATEMENT)
      .mockRejectedValueOnce(new ApiError(503, 'Invalid cashflow settings'))
    const { rerenderWith } = renderAt('/reports')
    await screen.findByText('Отчёт о прибылях и убытках')
    rerenderWith({ report: 'cashflow' })
    expect(await screen.findByText('Отчёт не настроен')).toBeInTheDocument()
    expect(screen.getByText('Обратитесь к администратору компании.')).toBeInTheDocument()
    expect(screen.queryByText('Отчёт о прибылях и убытках')).toBeNull()
  })

  it('downloads the report as Excel with the chosen units', async () => {
    getStatementMock.mockResolvedValue(STATEMENT)
    downloadStatementXlsxMock.mockResolvedValue({ blob: new Blob(['x']), filename: 'PnL_2026-08_demo_2026-09-23.xlsx' })
    renderAt('/reports?p=month&m=2026-08&u=k')
    await screen.findByText('Отчёт о прибылях и убытках')
    fireEvent.click(screen.getByRole('button', { name: /Excel/ }))
    await waitFor(() =>
      expect(saveFileMock).toHaveBeenCalledWith({ blob: expect.any(Blob), filename: 'PnL_2026-08_demo_2026-09-23.xlsx' }),
    )
    expect(downloadStatementXlsxMock).toHaveBeenCalledWith({
      template: 'professional',
      report: 'pnl',
      period: 'month',
      month: '2026-08',
      units: 'k',
    })
  })

  it('keeps the page working when the export fails', async () => {
    getStatementMock.mockResolvedValue(STATEMENT)
    let fail: (error: Error) => void = () => undefined
    downloadStatementXlsxMock.mockReturnValue(new Promise((_resolve, reject) => {
      fail = reject
    }))
    renderAt('/reports')
    await screen.findByText('Отчёт о прибылях и убытках')
    fireEvent.click(screen.getByRole('button', { name: /Excel/ }))
    await waitFor(() => expect(screen.getByRole('button', { name: /Excel/ })).toHaveClass('ant-btn-loading'))
    await act(async () => fail(new ApiError(502, 'n8n недоступен')))
    await waitFor(() => expect(notifyApiErrorMock).toHaveBeenCalledWith('n8n недоступен'))
    expect(screen.getByRole('button', { name: /Excel/ })).not.toHaveClass('ant-btn-loading')
    expect(saveFileMock).not.toHaveBeenCalled()
    expect(screen.getByText('Отчёт о прибылях и убытках')).toBeInTheDocument()
  })

  it('explains a connection failure in Russian', async () => {
    getStatementMock.mockResolvedValue(STATEMENT)
    downloadStatementXlsxMock.mockRejectedValue(new TypeError('Failed to fetch'))
    renderAt('/reports')
    await screen.findByText('Отчёт о прибылях и убытках')
    fireEvent.click(screen.getByRole('button', { name: /Excel/ }))
    await waitFor(() => expect(notifyApiErrorMock).toHaveBeenCalledWith(NETWORK_ERROR_MESSAGE))
  })

  it('shows one period at a time on a phone', async () => {
    getStatementMock.mockResolvedValue(STATEMENT)
    renderAt('/reports')
    await screen.findByText('Отчёт о прибылях и убытках')
    expect(screen.getByRole('button', { name: 'Банк: Сен* 1–23' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Банк: Авг' })).toBeNull()
    expect(screen.queryByText('Год назад')).toBeNull()
    fireEvent.click(screen.getByTitle('Авг'))
    expect(await screen.findByRole('button', { name: 'Банк: Авг' })).toBeInTheDocument()
  })

  it('shows no period chips when there is only one period', async () => {
    getStatementMock.mockResolvedValue({ ...STATEMENT, columns: STATEMENT.columns.filter((column) => column.key !== '2026-08') })
    renderAt('/reports')
    await screen.findByText('Отчёт о прибылях и убытках')
    expect(screen.queryByTitle('Сен*')).toBeNull()
    expect(screen.getByRole('button', { name: 'Банк: Сен* 1–23' })).toBeInTheDocument()
  })

  it('shows every period and the comparison on a wide screen', async () => {
    vi.spyOn(window, 'matchMedia').mockImplementation(
      (query: string) =>
        ({
          matches: query.includes('min-width'),
          media: query,
          onchange: null,
          addListener: () => undefined,
          removeListener: () => undefined,
          addEventListener: () => undefined,
          removeEventListener: () => undefined,
          dispatchEvent: () => false,
        }) as MediaQueryList,
    )
    getStatementMock.mockResolvedValue(STATEMENT)
    renderAt('/reports')
    await screen.findByText('Отчёт о прибылях и убытках')
    expect(screen.getByRole('button', { name: 'Банк: Авг' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Банк: Сен* 1–23' })).toBeInTheDocument()
    // rc-table repeats column titles in a hidden measure row, so ask for the visible header cell.
    expect(screen.getByRole('columnheader', { name: /Год назад/ })).toBeInTheDocument()
    expect(screen.queryByTitle('Авг')).toBeNull()
  })

  it('prints the statement with a header naming company, period, units and date', async () => {
    const print = vi.spyOn(window, 'print').mockImplementation(() => undefined)
    getStatementMock.mockResolvedValue(STATEMENT)
    const { container } = renderAt('/reports')
    await screen.findByText('Отчёт о прибылях и убытках')
    const header = container.querySelector('.rp-print-header')?.textContent ?? ''
    expect(header).toContain('ООО «Демо Трейд»')
    expect(header).toContain('Отчёт о прибылях и убытках · авг – 23 сен 2026 (01.08.2026 – 23.09.2026)')
    expect(header).toContain('млн сум · данные на 23.09.2026 14:32')
    fireEvent.click(screen.getByRole('button', { name: 'Ещё' }))
    fireEvent.click(await screen.findByText('Печать'))
    expect(print).toHaveBeenCalledTimes(1)
  })

  it('offers printing only for the statement, not for the operations list', async () => {
    getStatementMock.mockResolvedValue(STATEMENT)
    renderAt('/reports?view=operations')
    await screen.findByText(/^Операции ·/)
    fireEvent.click(screen.getByRole('button', { name: 'Ещё' }))
    expect(await screen.findByText('Как считается отчёт')).toBeInTheDocument()
    expect(screen.queryByText('Печать')).toBeNull()
  })

  it('starts a new report or period on its latest period chip', async () => {
    getStatementMock.mockResolvedValue(STATEMENT)
    const { rerenderWith } = renderAt('/reports')
    await screen.findByText('Отчёт о прибылях и убытках')
    fireEvent.click(screen.getByTitle('Авг'))
    expect(await screen.findByRole('button', { name: 'Банк: Авг' })).toBeInTheDocument()
    rerenderWith({ report: 'cashflow' })
    await waitFor(() => expect(getStatementMock).toHaveBeenCalledTimes(2))
    expect(await screen.findByRole('button', { name: 'Банк: Сен* 1–23' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Банк: Авг' })).toBeNull()
  })

  it('explains a missing report setup without technical details, which only admins see', async () => {
    getStatementMock.mockRejectedValue(new ApiError(503, 'No tenant_report_settings for tenant_id=1'))
    const { unmount } = renderAt('/reports')
    expect(await screen.findByText('Настройки отчёта не заданы или содержат ошибку.')).toBeInTheDocument()
    expect(screen.queryByText(/tenant_report_settings/)).toBeNull()
    unmount()
    useTenantAdminMock.mockReturnValue({ isAdmin: true, loading: false })
    renderAt('/reports')
    expect(await screen.findByText(/tenant_report_settings/)).toBeInTheDocument()
  })

  it('offers the link to copy by hand when the clipboard is blocked', async () => {
    getStatementMock.mockResolvedValue(STATEMENT)
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText: vi.fn().mockRejectedValue(new Error('denied')) },
      configurable: true,
    })
    const prompt = vi.spyOn(window, 'prompt').mockImplementation(() => null)
    renderAt('/reports')
    await screen.findByText('Отчёт о прибылях и убытках')
    fireEvent.click(screen.getByRole('button', { name: /Ссылка/ }))
    await waitFor(() => expect(prompt).toHaveBeenCalledTimes(1))
    expect(prompt.mock.calls[0][0]).toBe('Скопируйте ссылку')
    expect(prompt.mock.calls[0][1]).toBe(window.location.href)
    expect(notifyApiSuccessMock).not.toHaveBeenCalled()
  })

  it('opens a drill link on the unfinished month after the month has moved on', async () => {
    getStatementMock.mockResolvedValue(STATEMENT)
    renderAt('/reports?line=rev.bank&from=2026-09-01&to=2026-09-20')
    expect(await screen.findByText('Банк · 1–23 сен 2026')).toBeInTheDocument()
  })

  it('switches to the month a chart bar stands for, and back', async () => {
    getStatementMock.mockResolvedValue({ ...STATEMENT, chart: { ...STATEMENT.chart, months: [['2026-08'], ['2026-09']] } })
    renderAt('/reports')
    fireEvent.click(await screen.findByRole('button', { name: 'Авг: показать месяц' }))
    await waitFor(() =>
      expect(getStatementMock).toHaveBeenLastCalledWith(expect.objectContaining({ period: 'month', month: '2026-08' }), expect.anything()),
    )
    fireEvent.click(await screen.findByRole('button', { name: '← С начала года' }))
    await waitFor(() => expect(getStatementMock).toHaveBeenLastCalledWith(expect.objectContaining({ period: 'ytd' }), expect.anything()))
  })

  it('keeps the way back after a reload', async () => {
    getStatementMock.mockResolvedValue(STATEMENT)
    renderAt('/reports?p=month&m=2026-08&back=ytd,,,month')
    fireEvent.click(await screen.findByRole('button', { name: '← С начала года' }))
    await waitFor(() => expect(getStatementMock).toHaveBeenLastCalledWith(expect.objectContaining({ period: 'ytd' }), expect.anything()))
  })

  it('opens the requests of a vendor from the vendor list', async () => {
    getStatementMock.mockResolvedValue(STATEMENT)
    getStatementVendorsMock.mockResolvedValue({
      total: '790000.00',
      count: 1,
      items: [{ vendor: 'ООО Офис', amount: '790000.00', requests: 2, line_id: 'opex.11111111', line_label: 'Маркетинг' }],
    })
    renderAt('/reports')
    fireEvent.click(await screen.findByRole('button', { name: /ООО Офис/ }))
    expect(await screen.findByText(/^ООО Офис · /)).toBeInTheDocument()
    expect(screen.getByText('Прибыли и убытки › Поставщики')).toBeInTheDocument()
    expect(getStatementVendorsMock).toHaveBeenCalledWith(
      expect.objectContaining({ from: '2026-08-01', to: '2026-09-23', limit: 6 }),
      expect.anything(),
    )
  })

  it('opens the operations behind a KPI tile', async () => {
    getStatementMock.mockResolvedValue(STATEMENT)
    renderAt('/reports')
    fireEvent.click(await screen.findByRole('button', { name: 'Выручка: показать состав' }))
    expect(await screen.findByText(/^Выручка · /)).toBeInTheDocument()
  })

  it('asks for the report of its card', async () => {
    getStatementMock.mockResolvedValue({ ...STATEMENT, report: 'cashflow' })
    renderAt('/reports', { report: 'cashflow' })
    await waitFor(() =>
      expect(getStatementMock).toHaveBeenCalledWith(expect.objectContaining({ report: 'cashflow' }), expect.anything()),
    )
  })

  it('opens the rules of the report from the menu', async () => {
    useTenantAdminMock.mockReturnValue({ isAdmin: true, loading: false })
    getStatementMock.mockResolvedValue(STATEMENT)
    const onOpenRules = vi.fn()
    renderAt('/reports', { onOpenRules })
    await screen.findByText('Отчёт о прибылях и убытках')
    fireEvent.click(screen.getByRole('button', { name: 'Ещё' }))
    fireEvent.click(await screen.findByText('Настройки отчёта'))
    expect(onOpenRules).toHaveBeenCalledTimes(1)
  })

  it('loads the report again after its rules are saved', async () => {
    getStatementMock.mockResolvedValue(STATEMENT)
    const { rerenderWith } = renderAt('/reports')
    await screen.findByText('Отчёт о прибылях и убытках')
    rerenderWith({ rulesVersion: 1 })
    await waitFor(() => expect(getStatementMock).toHaveBeenCalledTimes(2))
  })
})
