import type { ReportKind, ReportTemplatesResponse } from '../../lib/reportsApi'
import { FALLBACK_TEMPLATE, REPORT_TEMPLATE_REGISTRY } from './templates/registry'
import type { ReportCardInfo, ReportTemplateDefinition } from './templates/types'

export type ReportCard = {
  template: string
  templateLabel: string
  report: ReportKind
  title: string
  description: string
  /** `/reports/<template>/<report>` */
  path: string
}

export type ReportCardResolution =
  | { status: 'ok'; card: ReportCard }
  | { status: 'unknown' }
  | { status: 'not-allowed'; templateLabel: string }

type TemplateEntry = { key: string; label?: string; reports?: ReportKind[] }

// Own keys only: a path such as /reports/classic/__proto__ must not reach Object.prototype.
function definitionOf(key: string): ReportTemplateDefinition | null {
  return Object.hasOwn(REPORT_TEMPLATE_REGISTRY, key) ? REPORT_TEMPLATE_REGISTRY[key] : null
}

function cardInfo(definition: ReportTemplateDefinition, report: string): ReportCardInfo | null {
  return Object.hasOwn(definition.reports, report) ? (definition.reports[report as ReportKind] ?? null) : null
}

export function reportPath(template: string, report: string): string {
  return `/reports/${encodeURIComponent(template)}/${encodeURIComponent(report)}`
}

/** Allowed templates with the «show first» one in front; only the fallback template when the list is unknown. */
function templatesInOrder(templates: ReportTemplatesResponse | null): TemplateEntry[] {
  if (!templates) return [{ key: FALLBACK_TEMPLATE }]
  const first = templates.allowed.filter((template) => template.key === templates.default)
  return [...first, ...templates.allowed.filter((template) => template.key !== templates.default)]
}

/** Cards of «Отчёты» in page order: one per report of every allowed template the page knows. */
export function buildReportCards(templates: ReportTemplatesResponse | null): ReportCard[] {
  const cards: ReportCard[] = []
  for (const entry of templatesInOrder(templates)) {
    const definition = definitionOf(entry.key)
    if (!definition) continue
    for (const [report, info] of Object.entries(definition.reports) as [ReportKind, ReportCardInfo | undefined][]) {
      if (!info || (entry.reports && !entry.reports.includes(report))) continue
      cards.push({
        template: definition.key,
        templateLabel: entry.label || definition.label,
        report,
        title: info.title,
        description: info.description,
        path: reportPath(definition.key, report),
      })
    }
  }
  return cards
}

/** What `/reports/:template/:report` shows: its card, «не найден» for an unknown pair, «недоступен» for a template the company has not allowed. */
export function resolveReportCard(
  templates: ReportTemplatesResponse | null,
  template: string,
  report: string,
): ReportCardResolution {
  const definition = definitionOf(template)
  if (!definition || !cardInfo(definition, report)) return { status: 'unknown' }
  const card = buildReportCards(templates).find((candidate) => candidate.template === template && candidate.report === report)
  return card ? { status: 'ok', card } : { status: 'not-allowed', templateLabel: definition.label }
}

/** Templates that put any of these parameters in the address of «Отчёты» before the cards. */
function templatesThatWrote(params: URLSearchParams): string[] {
  return Object.values(REPORT_TEMPLATE_REGISTRY)
    .filter((definition) => definition.legacyParams?.some((key) => params.has(key)))
    .map((definition) => definition.key)
}

/**
 * A link from before the cards (`/reports?t=…&r=…&…`) → the card's own page with every other parameter; null for `/reports`
 * without such parameters. The old address bar named no template: a link without `t` opens the template that wrote its
 * parameters when it is allowed, else the «show first» one.
 */
export function legacyReportPath(params: URLSearchParams, templates: ReportTemplatesResponse | null): string | null {
  const writers = templatesThatWrote(params)
  if (!params.has('t') && writers.length === 0) return null
  const allowed = templatesInOrder(templates).map((entry) => entry.key)
  // `.` and `..` cannot be a path segment (the browser drops them), so such a link names no template.
  const named = (params.get('t') ?? '').replace(/^\.{1,2}$/, '')
  const template = named || writers.find((key) => allowed.includes(key)) || templates?.default || FALLBACK_TEMPLATE
  // Old links only knew these two reports; anything else opened PnL.
  const report: ReportKind = params.get('r') === 'cashflow' ? 'cashflow' : 'pnl'
  const rest = new URLSearchParams(params)
  rest.delete('t')
  rest.delete('r')
  const query = rest.toString()
  return `${reportPath(template, report)}${query ? `?${query}` : ''}`
}
