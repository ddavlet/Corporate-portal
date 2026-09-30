import type { ReportTemplateDefinition } from './types'

/** The template shown when the template list cannot be loaded. */
export const FALLBACK_TEMPLATE = 'classic'

/** Add a template here and under templates/<key>/; its cards and pages appear by themselves. Keys match the backend REPORT_TEMPLATES. */
export const REPORT_TEMPLATE_REGISTRY: Record<string, ReportTemplateDefinition> = {
  classic: {
    key: 'classic',
    label: 'Классический',
    reports: {
      pnl: { title: 'PnL', description: 'Помесячная таблица прибылей и убытков и список операций.' },
      cashflow: { title: 'Cashflow', description: 'Помесячная таблица движения денег и список операций.' },
    },
    load: () => import('./classic/ClassicReportTemplate').then((module) => ({ default: module.ClassicReportTemplate })),
  },
  professional: {
    key: 'professional',
    label: 'Профессиональный',
    reports: {
      pnl: { title: 'Прибыли и убытки', description: 'Показатели, график и отчёт о прибылях и убытках с итогами и сравнением.' },
      cashflow: { title: 'Движение денег', description: 'Показатели, график и отчёт о движении денег с остатками и сравнением.' },
    },
    transientParams: ['line', 'from', 'to', 'vendor'],
    legacyParams: ['r', 'p', 'y', 'm', 'g', 'cmp', 'u', 'view', 'open', 'line', 'from', 'to', 'vendor', 'back'],
    load: () =>
      import('./professional/ProfessionalReportTemplate').then((module) => ({ default: module.ProfessionalReportTemplate })),
  },
}
