import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const getStatementMock = vi.fn()
const downloadStatementXlsxMock = vi.fn()
vi.mock('../../../../lib/reportsApi', () => ({
  getStatement: (...args: unknown[]) => getStatementMock(...args),
  // Pending: the «Операции» view only needs to mount.
  getStatementLines: () => new Promise(() => undefined),
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

function renderAt(url: string) {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <ProfessionalReportTemplate templateSwitcher={null} />
    </MemoryRouter>,
  )
}

describe('ProfessionalReportTemplate', () => {
  beforeEach(() => {
    getStatementMock.mockReset()
    downloadStatementXlsxMock.mockReset()
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

  it('explains that the report is not configured', async () => {
    useTenantAdminMock.mockReturnValue({ isAdmin: true, loading: false })
    getStatementMock.mockRejectedValue(new ApiError(503, 'No tenant_report_settings for tenant_id=1'))
    renderAt('/reports')
    expect(await screen.findByText('Отчёт не настроен')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Настроить отчёт' })).toBeInTheDocument()
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

  it('copies a link that opens this template for the recipient', async () => {
    getStatementMock.mockResolvedValue(STATEMENT)
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    renderAt('/reports?p=month&m=2026-08')
    await screen.findByText('Отчёт о прибылях и убытках')
    fireEvent.click(screen.getByRole('button', { name: /Ссылка/ }))
    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1))
    expect(new URL(String(writeText.mock.calls[0][0])).searchParams.get('t')).toBe('professional')
  })

  it('does not keep the previous report on screen when the next one cannot be built', async () => {
    getStatementMock
      .mockResolvedValueOnce(STATEMENT)
      .mockRejectedValueOnce(new ApiError(503, 'Invalid cashflow settings'))
    renderAt('/reports')
    await screen.findByText('Отчёт о прибылях и убытках')
    fireEvent.click(screen.getByTitle('Движение денег'))
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
    expect(screen.getByText('Год назад')).toBeInTheDocument()
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
    renderAt('/reports')
    await screen.findByText('Отчёт о прибылях и убытках')
    fireEvent.click(screen.getByTitle('Авг'))
    expect(await screen.findByRole('button', { name: 'Банк: Авг' })).toBeInTheDocument()
    fireEvent.click(screen.getByTitle('Движение денег'))
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
    expect(new URL(String(prompt.mock.calls[0][1])).searchParams.get('t')).toBe('professional')
    expect(notifyApiSuccessMock).not.toHaveBeenCalled()
  })

  it('opens a drill link on the unfinished month after the month has moved on', async () => {
    getStatementMock.mockResolvedValue(STATEMENT)
    renderAt('/reports?line=rev.bank&from=2026-09-01&to=2026-09-20')
    expect(await screen.findByText('Банк · 1–23 сен 2026')).toBeInTheDocument()
  })
})
