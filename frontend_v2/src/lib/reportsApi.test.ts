import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('./apiNotify', () => ({
  notifyApiError: vi.fn(),
  notifyNetworkError: vi.fn(),
  notifyApiSuccess: vi.fn(),
}))

import { notifyApiError } from './apiNotify'
import {
  downloadLinesXlsx,
  downloadStatementXlsx,
  filenameFromContentDisposition,
  getReportRequestDetail,
  getStatement,
  getStatementLines,
  statementExportSearchParams,
  statementLinesSearchParams,
  statementSearchParams,
  updateReportTemplates,
} from './reportsApi'
import { createJsonResponse, createStorageMock, setWindowLocation } from '../test/helpers'

function fileResponse(disposition: string | null): Response {
  const headers = new Headers()
  if (disposition) headers.set('Content-Disposition', disposition)
  return { ok: true, status: 200, headers, blob: async () => new Blob(['xlsx']) } as unknown as Response
}

describe('reportsApi', () => {
  const fetchMock = vi.fn()

  beforeEach(() => {
    setWindowLocation('/')
    Object.defineProperty(globalThis, 'localStorage', { value: createStorageMock(), configurable: true })
    Object.defineProperty(globalThis, 'sessionStorage', { value: createStorageMock(), configurable: true })
    Object.defineProperty(globalThis, 'fetch', { value: fetchMock, configurable: true })
    fetchMock.mockReset()
  })

  it('builds statement params, leaving out what is not set', () => {
    expect(statementSearchParams({ template: 'professional', report: 'pnl', period: 'ytd' }).toString()).toBe(
      'template=professional&report=pnl&period=ytd',
    )
    expect(
      statementSearchParams({
        template: 'professional',
        report: 'cashflow',
        period: 'month',
        month: '2026-08',
        granularity: 'quarter',
        compare: 'yoy',
        refresh: true,
      }).toString(),
    ).toBe('template=professional&report=cashflow&period=month&month=2026-08&granularity=quarter&compare=yoy&refresh=1')
  })

  it('builds drill-down params with from/to', () => {
    expect(
      statementLinesSearchParams({
        template: 'professional',
        report: 'pnl',
        line: 'opex',
        from: '2026-08-01',
        to: '2026-08-31',
        q: 'аренда',
        page: 2,
        pageSize: 50,
      }).toString(),
    ).toBe(
      'template=professional&report=pnl&line=opex&from=2026-08-01&to=2026-08-31&q=%D0%B0%D1%80%D0%B5%D0%BD%D0%B4%D0%B0&page=2&page_size=50',
    )
  })

  it('requests the statement with the query in the URL', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse(200, { report: 'pnl', rows: [] }))
    const data = await getStatement({ template: 'professional', report: 'pnl', period: 'ytd', compare: 'yoy' })
    expect(fetchMock.mock.calls[0][0]).toBe(
      '/api/reports/statement/?template=professional&report=pnl&period=ytd&compare=yoy',
    )
    expect(data.report).toBe('pnl')
  })

  it('requests drill-down lines', async () => {
    fetchMock.mockResolvedValueOnce(
      createJsonResponse(200, { line: 'rev', total: '10.00', count: 1, page: 1, page_size: 50, items: [] }),
    )
    const data = await getStatementLines({
      template: 'professional',
      report: 'pnl',
      line: 'rev',
      from: '2026-08-01',
      to: '2026-08-31',
    })
    expect(fetchMock.mock.calls[0][0]).toBe(
      '/api/reports/statement/lines/?template=professional&report=pnl&line=rev&from=2026-08-01&to=2026-08-31',
    )
    expect(data.total).toBe('10.00')
  })

  it('sends template settings as PATCH JSON', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse(200, { default: 'classic', allowed: [], available: [] }))
    await updateReportTemplates({ default_template: 'classic', allowed_templates: ['classic'] })
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/reports/templates/')
    expect(init.method).toBe('PATCH')
    expect(JSON.parse(init.body)).toEqual({ default_template: 'classic', allowed_templates: ['classic'] })
  })

  it('throws ApiError with the HTTP status', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse(403, { detail: 'Шаблон недоступен для этой компании.' }))
    await expect(getStatement({ template: 'professional', report: 'pnl', period: 'ytd' })).rejects.toMatchObject({
      name: 'ApiError',
      status: 403,
      message: 'Шаблон недоступен для этой компании.',
    })
  })

  it('leaves out the line when listing every section and passes the source filter', () => {
    expect(
      statementLinesSearchParams({ template: 'professional', report: 'pnl', from: '2026-08-01', to: '2026-08-31', source: 'bank' }).toString(),
    ).toBe('template=professional&report=pnl&from=2026-08-01&to=2026-08-31&source=bank')
  })

  it('does not show a global error toast; the page handles errors', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse(503, { detail: 'No tenant_report_settings' }))
    await expect(getStatement({ template: 'professional', report: 'pnl', period: 'ytd' })).rejects.toMatchObject({ status: 503 })
    expect(notifyApiError).not.toHaveBeenCalled()
  })

  it('loads a request for the drill-down panel', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse(200, { id: 4812 }))
    const data = await getReportRequestDetail(4812)
    expect(fetchMock.mock.calls[0][0]).toBe('/api/requests/4812/')
    expect(data).toEqual({ id: 4812 })
  })

  it('adds units to the export query', () => {
    expect(
      statementExportSearchParams({ template: 'professional', report: 'pnl', period: 'month', month: '2026-08', units: 'k' }).toString(),
    ).toBe('template=professional&report=pnl&period=month&month=2026-08&units=k')
  })

  it('reads the file name from Content-Disposition', () => {
    expect(
      filenameFromContentDisposition(`attachment; filename*=utf-8''PnL_%D0%9E%D0%BF%D0%B5%D1%80%D0%B0%D1%86%D0%B8%D0%B8.xlsx`, 'x.xlsx'),
    ).toBe('PnL_Операции.xlsx')
    expect(filenameFromContentDisposition('attachment; filename="PnL_2026-YTD_demo_2026-09-23.xlsx"', 'x.xlsx')).toBe(
      'PnL_2026-YTD_demo_2026-09-23.xlsx',
    )
    expect(filenameFromContentDisposition(null, 'pnl.xlsx')).toBe('pnl.xlsx')
  })

  it('downloads the statement workbook without asking for JSON', async () => {
    fetchMock.mockResolvedValueOnce(fileResponse('attachment; filename="PnL_2026-08_demo_2026-09-23.xlsx"'))
    const file = await downloadStatementXlsx({ template: 'professional', report: 'pnl', period: 'month', month: '2026-08', units: 'm' })
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/reports/statement/export/?template=professional&report=pnl&period=month&month=2026-08&units=m')
    expect((init.headers as Headers).get('Accept')).toBeNull()
    expect(file.filename).toBe('PnL_2026-08_demo_2026-09-23.xlsx')
    expect(file.blob).toBeInstanceOf(Blob)
  })

  it('downloads the operations of a cell with the current search', async () => {
    fetchMock.mockResolvedValueOnce(fileResponse(null))
    const file = await downloadLinesXlsx({ template: 'professional', report: 'pnl', line: 'rev', from: '2026-08-01', to: '2026-08-31', q: 'click' })
    expect(fetchMock.mock.calls[0][0]).toBe(
      '/api/reports/statement/lines/export/?template=professional&report=pnl&line=rev&from=2026-08-01&to=2026-08-31&q=click',
    )
    expect(file.filename).toBe('pnl-operations.xlsx')
  })

  it('turns an export error into ApiError without a toast', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse(503, { detail: 'No tenant_report_settings' }))
    await expect(downloadStatementXlsx({ template: 'professional', report: 'pnl', period: 'ytd', units: 'm' })).rejects.toMatchObject({
      status: 503,
      message: 'No tenant_report_settings',
    })
    expect(notifyApiError).not.toHaveBeenCalled()
  })
})
