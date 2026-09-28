import type { ReportKind } from '../../lib/reportsApi'

export const FALLBACK_TEMPLATE = 'classic'

export type TemplateResolutionInput = {
  requested: string | null
  preferred: string | null
  tenantDefault: string | null
  allowed: string[]
  supports: Record<string, ReportKind[]>
  report: ReportKind
  labels: Record<string, string>
}

export type TemplateResolution = { key: string; notice: string | null }

/** Link → user preference → tenant default → Classic; only allowed templates that support the report. */
export function resolveReportTemplate(input: TemplateResolutionInput): TemplateResolution {
  const usable = (key: string | null): key is string =>
    Boolean(key && input.allowed.includes(key) && input.supports[key]?.includes(input.report))
  const fallback = [input.preferred, input.tenantDefault].find(usable) ?? FALLBACK_TEMPLATE
  if (usable(input.requested)) return { key: input.requested, notice: null }
  if (input.requested) {
    const asked = input.labels[input.requested] ?? input.requested
    const shown = input.labels[fallback] ?? fallback
    return { key: fallback, notice: `Шаблон «${asked}» недоступен, показан «${shown}».` }
  }
  return { key: fallback, notice: null }
}
