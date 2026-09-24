import { ApiError, apiFetch, parseErrorBody } from './api'

const BASE = '/api/reports'

/** Report pages render their own error states, so apiFetch must not toast. */
const SILENT = { silent: true } as const

/** File downloads: no JSON Accept header, and errors are shown by the page. */
const FILE_DOWNLOAD = { silent: true, omitAcceptJson: true } as const

export type ReportKind = 'pnl' | 'cashflow'

export type ReportTemplateInfo = {
  key: string
  label: string
  description: string
  reports: ReportKind[]
  engine: 'legacy' | 'statement'
}

export type ReportTemplatesResponse = {
  default: string
  allowed: ReportTemplateInfo[]
  available: ReportTemplateInfo[]
}

export type ReportTemplateSettingsPayload = { default_template: string; allowed_templates: string[] }

export type ReportUnits = 'sum' | 'k' | 'm'

export type StatementPeriod = 'month' | 'ytd' | 'year' | 'ltm'

export type StatementQuery = {
  template: string
  report: ReportKind
  period: StatementPeriod
  year?: number
  month?: string
  granularity?: 'month' | 'quarter'
  compare?: 'none' | 'yoy'
  refresh?: boolean
}

export type StatementColumn = {
  key: string
  kind: 'period' | 'total' | 'compare' | 'delta'
  label: string
  sublabel: string
  months: string[]
  from: string | null
  to: string | null
  partial: boolean
  before_start: boolean
  starts_before_data: boolean
  delta_of: [string, string] | null
}

export type StatementDelta = { pct: string } | { pp: string } | null

export type StatementPolarity = 'income' | 'expense' | 'neutral' | 'result'

export type StatementRow = {
  id: string
  parent: string | null
  kind: 'group' | 'line' | 'result' | 'ratio' | 'balance'
  label: string
  polarity: StatementPolarity
  depth: number
  drillable: boolean
  strong: boolean
  hint: string
  separator_before: boolean
  values: Record<string, string | null>
  deltas: Record<string, StatementDelta>
}

export type StatementKpi = {
  id: string
  label: string
  polarity: StatementPolarity
  value: string | null
  ratio: string | null
  comparisons: { key: string; label: string; value: string | null; delta_pct: string | null }[]
  spark: (string | null)[]
}

export type StatementChart = {
  labels: string[]
  partial: boolean[]
  inflow: (string | null)[]
  outflow: (string | null)[]
  net: (string | null)[]
}

export type StatementMeta = {
  company: string | null
  source: string
  generated_at: string
  start_month: string
  today: string
  period_label: string
}

export type StatementWarning = { code: string; count: number; amount: string; purposes: string[] }

export type StatementResponse = {
  report: ReportKind
  template: string
  meta: StatementMeta
  columns: StatementColumn[]
  rows: StatementRow[]
  kpis: StatementKpi[]
  chart: StatementChart
  methodology: { label: string; text: string }[]
  warnings: StatementWarning[]
}

export type StatementLinesQuery = {
  template: string
  report: ReportKind
  line?: string
  source?: StatementLineItem['source']
  from: string
  to: string
  q?: string
  page?: number
  pageSize?: number
}

export type StatementLineItem = {
  entry_id: string
  date: string
  amount: string
  section: 'revenue' | 'operational' | 'other' | 'invest_returns'
  source: 'bank' | 'cash' | 'request' | 'invest_return' | 'unknown'
  category: string
  title: string
  counterparty: string
  request_id: number | null
  channel: string
  line_id: string
  line_label: string
  amortization: { index: number; count: number } | null
}

export type StatementLinesResponse = {
  line: string
  total: string
  count: number
  page: number
  page_size: number
  items: StatementLineItem[]
}

export type StatementExportQuery = Omit<StatementQuery, 'refresh'> & { units: ReportUnits }

export type StatementLinesExportQuery = Omit<StatementLinesQuery, 'page' | 'pageSize'>

export type DownloadedFile = { blob: Blob; filename: string }

async function readJson<T>(res: Response): Promise<T> {
  if (!res.ok) throw new ApiError(res.status, await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as T | null
  if (json === null) throw new ApiError(res.status, 'Пустой ответ от сервера')
  return json
}

export function statementSearchParams(query: StatementQuery): URLSearchParams {
  const params = new URLSearchParams({ template: query.template, report: query.report, period: query.period })
  if (query.year !== undefined) params.set('year', String(query.year))
  if (query.month) params.set('month', query.month)
  if (query.granularity) params.set('granularity', query.granularity)
  if (query.compare) params.set('compare', query.compare)
  if (query.refresh) params.set('refresh', '1')
  return params
}

export function statementLinesSearchParams(query: StatementLinesQuery): URLSearchParams {
  const params = new URLSearchParams({ template: query.template, report: query.report })
  if (query.line) params.set('line', query.line)
  params.set('from', query.from)
  params.set('to', query.to)
  if (query.source) params.set('source', query.source)
  if (query.q) params.set('q', query.q)
  if (query.page) params.set('page', String(query.page))
  if (query.pageSize) params.set('page_size', String(query.pageSize))
  return params
}

export function statementExportSearchParams(query: StatementExportQuery): URLSearchParams {
  const params = statementSearchParams(query)
  params.set('units', query.units)
  return params
}

/** RFC 6266: `filename*` (UTF-8) wins over `filename`; the fallback covers a missing header. */
export function filenameFromContentDisposition(header: string | null, fallback: string): string {
  if (!header) return fallback
  const encoded = /filename\*\s*=\s*utf-8''([^;]+)/i.exec(header)
  if (encoded) {
    try {
      return decodeURIComponent(encoded[1].trim())
    } catch {
      // Malformed percent-encoding: use the plain name below.
    }
  }
  const plain = /filename\s*=\s*"([^"]*)"|filename\s*=\s*([^;]+)/i.exec(header)
  const name = (plain?.[1] ?? plain?.[2] ?? '').trim()
  return name || fallback
}

async function readFile(res: Response, fallback: string): Promise<DownloadedFile> {
  if (!res.ok) throw new ApiError(res.status, await parseErrorBody(res))
  return {
    blob: await res.blob(),
    filename: filenameFromContentDisposition(res.headers.get('Content-Disposition'), fallback),
  }
}

export async function getReportTemplates(): Promise<ReportTemplatesResponse> {
  return readJson<ReportTemplatesResponse>(await apiFetch(`${BASE}/templates/`, {}, SILENT))
}

export async function updateReportTemplates(payload: ReportTemplateSettingsPayload): Promise<ReportTemplatesResponse> {
  const res = await apiFetch(
    `${BASE}/templates/`,
    { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) },
    SILENT,
  )
  return readJson<ReportTemplatesResponse>(res)
}

export async function getStatement(query: StatementQuery, signal?: AbortSignal): Promise<StatementResponse> {
  return readJson<StatementResponse>(await apiFetch(`${BASE}/statement/?${statementSearchParams(query)}`, { signal }, SILENT))
}

export async function getStatementLines(
  query: StatementLinesQuery,
  signal?: AbortSignal,
): Promise<StatementLinesResponse> {
  return readJson<StatementLinesResponse>(
    await apiFetch(`${BASE}/statement/lines/?${statementLinesSearchParams(query)}`, { signal }, SILENT),
  )
}

/** Full request card for the drill-down panel (shape of `RequestDetail` in ui/requests). */
export async function getReportRequestDetail(requestId: number): Promise<unknown> {
  return readJson<unknown>(await apiFetch(`/api/requests/${requestId}/`, {}, SILENT))
}

export async function downloadStatementXlsx(query: StatementExportQuery, signal?: AbortSignal): Promise<DownloadedFile> {
  const res = await apiFetch(`${BASE}/statement/export/?${statementExportSearchParams(query)}`, { signal }, FILE_DOWNLOAD)
  return readFile(res, `${query.report}.xlsx`)
}

export async function downloadLinesXlsx(query: StatementLinesExportQuery, signal?: AbortSignal): Promise<DownloadedFile> {
  const res = await apiFetch(`${BASE}/statement/lines/export/?${statementLinesSearchParams(query)}`, { signal }, FILE_DOWNLOAD)
  return readFile(res, `${query.report}-operations.xlsx`)
}
