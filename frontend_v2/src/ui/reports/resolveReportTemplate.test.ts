import { describe, expect, it } from 'vitest'
import { resolveReportTemplate, type TemplateResolutionInput } from './resolveReportTemplate'

const base: TemplateResolutionInput = {
  requested: null,
  preferred: null,
  tenantDefault: 'classic',
  allowed: ['classic', 'professional'],
  supports: { classic: ['pnl', 'cashflow'], professional: ['pnl', 'cashflow'] },
  report: 'pnl',
  labels: { classic: 'Классический', professional: 'Профессиональный' },
}

describe('resolveReportTemplate', () => {
  it('prefers the link, then the user, then the tenant default', () => {
    expect(resolveReportTemplate({ ...base, requested: 'professional' })).toEqual({ key: 'professional', notice: null })
    expect(resolveReportTemplate({ ...base, preferred: 'professional' })).toEqual({ key: 'professional', notice: null })
    expect(resolveReportTemplate({ ...base, tenantDefault: 'professional' })).toEqual({ key: 'professional', notice: null })
  })

  it('explains when the linked template is not allowed', () => {
    expect(resolveReportTemplate({ ...base, requested: 'professional', allowed: ['classic'] })).toEqual({
      key: 'classic',
      notice: 'Шаблон «Профессиональный» недоступен, показан «Классический».',
    })
  })

  it('skips templates that do not support the report', () => {
    const input: TemplateResolutionInput = {
      ...base,
      preferred: 'professional',
      report: 'cashflow',
      supports: { classic: ['pnl', 'cashflow'], professional: ['pnl'] },
    }
    expect(resolveReportTemplate(input).key).toBe('classic')
  })

  it('falls back to classic when nothing else is usable', () => {
    expect(resolveReportTemplate({ ...base, tenantDefault: 'ghost', allowed: ['ghost'] }).key).toBe('classic')
  })
})
