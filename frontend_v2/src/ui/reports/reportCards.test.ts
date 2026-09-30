import { describe, expect, it } from 'vitest'
import type { ReportTemplateInfo, ReportTemplatesResponse } from '../../lib/reportsApi'
import { buildReportCards, legacyReportPath, reportPath, resolveReportCard } from './reportCards'

const info = (key: string, label: string, reports: ReportTemplateInfo['reports'] = ['pnl', 'cashflow']): ReportTemplateInfo => ({
  key,
  label,
  description: '',
  reports,
  engine: key === 'classic' ? 'legacy' : 'statement',
})
const classic = info('classic', 'Классический')
const professional = info('professional', 'Профессиональный')
const templates = (defaultKey: string, allowed: ReportTemplateInfo[]): ReportTemplatesResponse => ({
  default: defaultKey,
  allowed,
  available: [classic, professional],
})
const both = templates('professional', [classic, professional])

describe('buildReportCards', () => {
  it('shows every report of every allowed template, the «show first» template first', () => {
    const cards = buildReportCards(both)
    expect(cards.map((card) => `${card.template}/${card.report}:${card.title}`)).toEqual([
      'professional/pnl:Прибыли и убытки',
      'professional/cashflow:Движение денег',
      'classic/pnl:PnL',
      'classic/cashflow:Cashflow',
    ])
    expect(cards[0].path).toBe('/reports/professional/pnl')
    expect(cards[0].templateLabel).toBe('Профессиональный')
  })

  it('puts Classic first when it is the template shown first', () => {
    expect(buildReportCards(templates('classic', [classic, professional]))[0].path).toBe('/reports/classic/pnl')
  })

  it('shows only the cards of allowed templates', () => {
    expect(buildReportCards(templates('classic', [classic])).map((card) => card.title)).toEqual(['PnL', 'Cashflow'])
  })

  it('skips templates the page does not know and reports a template does not support', () => {
    const cards = buildReportCards(templates('classic', [info('classic', 'Классический', ['pnl']), info('ghost', 'Призрак')]))
    expect(cards.map((card) => `${card.template}/${card.report}`)).toEqual(['classic/pnl'])
  })

  it('falls back to the Classic cards without the template list', () => {
    expect(buildReportCards(null).map((card) => card.path)).toEqual(['/reports/classic/pnl', '/reports/classic/cashflow'])
  })
})

describe('resolveReportCard', () => {
  it('finds the card of the path', () => {
    const resolution = resolveReportCard(both, 'professional', 'cashflow')
    expect(resolution.status === 'ok' && resolution.card.title).toBe('Движение денег')
  })

  it('does not find what the registry does not have, object built-ins included', () => {
    for (const [template, report] of [
      ['professional', 'ghost'],
      ['ghost', 'pnl'],
      ['classic', '__proto__'],
      ['constructor', 'pnl'],
      ['classic', 'toString'],
    ]) {
      expect(resolveReportCard(both, template, report)).toEqual({ status: 'unknown' })
    }
  })

  it('names a template the company has not allowed', () => {
    expect(resolveReportCard(templates('classic', [classic]), 'professional', 'pnl')).toEqual({
      status: 'not-allowed',
      templateLabel: 'Профессиональный',
    })
  })

  it('allows only Classic without the template list', () => {
    expect(resolveReportCard(null, 'classic', 'pnl').status).toBe('ok')
    expect(resolveReportCard(null, 'professional', 'pnl').status).toBe('not-allowed')
  })
})

describe('legacyReportPath', () => {
  it('leaves /reports alone', () => {
    expect(legacyReportPath(new URLSearchParams(''), both)).toBeNull()
  })

  it('keeps the period and the open drill-down of an old link', () => {
    const params = new URLSearchParams('t=professional&r=cashflow&p=month&m=2026-08&line=rev.bank&from=2026-08-01&to=2026-08-31')
    expect(legacyReportPath(params, both)).toBe(
      '/reports/professional/cashflow?p=month&m=2026-08&line=rev.bank&from=2026-08-01&to=2026-08-31',
    )
  })

  // Before the cards the address bar named no template, and only «Профессиональный» put its view there.
  it('opens a link without `t` in the template that wrote its parameters', () => {
    const params = new URLSearchParams('p=month&m=2026-08&line=rev.bank&from=2026-08-01&to=2026-08-31')
    expect(legacyReportPath(params, templates('classic', [classic, professional]))).toBe(
      '/reports/professional/pnl?p=month&m=2026-08&line=rev.bank&from=2026-08-01&to=2026-08-31',
    )
    expect(legacyReportPath(new URLSearchParams('r=cashflow'), templates('classic', [classic, professional]))).toBe(
      '/reports/professional/cashflow',
    )
  })

  it('opens the «show first» template when the template of a link without `t` is not allowed', () => {
    expect(legacyReportPath(new URLSearchParams('p=month&m=2026-08'), templates('classic', [classic]))).toBe(
      '/reports/classic/pnl?p=month&m=2026-08',
    )
    expect(legacyReportPath(new URLSearchParams('r=cashflow'), null)).toBe('/reports/classic/cashflow')
  })

  it('treats a template of dots as none: the browser would drop it from the path', () => {
    expect(legacyReportPath(new URLSearchParams('t=..&r=cashflow'), both)).toBe('/reports/professional/cashflow')
    expect(legacyReportPath(new URLSearchParams('t=.'), templates('classic', [classic, professional]))).toBe(
      '/reports/classic/pnl',
    )
  })

  it('leaves /reports alone when its parameters are not those of an old report link', () => {
    expect(legacyReportPath(new URLSearchParams('utm_source=mail'), both)).toBeNull()
  })

  it('keeps an odd template inside /reports', () => {
    expect(legacyReportPath(new URLSearchParams('t=a/b&r=x'), both)).toBe('/reports/a%2Fb/pnl')
    expect(reportPath('a/b', 'pnl')).toBe('/reports/a%2Fb/pnl')
  })
})
