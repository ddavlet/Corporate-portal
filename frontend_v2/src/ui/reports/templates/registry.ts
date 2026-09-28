import type { ReportTemplateDefinition } from './types'

/** Add a template here and under templates/<key>/; nothing else changes. Keys match the backend REPORT_TEMPLATES. */
export const REPORT_TEMPLATE_REGISTRY: Record<string, ReportTemplateDefinition> = {
  classic: {
    key: 'classic',
    label: 'Классический',
    supports: ['pnl', 'cashflow'],
    load: () => import('./classic/ClassicReportTemplate').then((module) => ({ default: module.ClassicReportTemplate })),
  },
  professional: {
    key: 'professional',
    label: 'Профессиональный',
    supports: ['pnl', 'cashflow'],
    load: () =>
      import('./professional/ProfessionalReportTemplate').then((module) => ({ default: module.ProfessionalReportTemplate })),
  },
}
