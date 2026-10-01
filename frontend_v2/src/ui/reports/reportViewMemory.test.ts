import { afterEach, describe, expect, it } from 'vitest'
import { withoutSessionStorage } from '../../test/helpers'
import { rememberView, rememberedView, viewToRemember } from './reportViewMemory'

describe('report view memory', () => {
  afterEach(() => sessionStorage.clear())

  it('keeps the view of each card apart, without its transient parameters', () => {
    rememberView('professional', 'pnl', '?p=month&m=2026-08&line=rev&from=2026-08-01&to=2026-08-31', ['line', 'from', 'to', 'vendor'])
    rememberView('classic', 'pnl', '?y=2025&q=аренда')
    expect(rememberedView('professional', 'pnl')).toBe('?p=month&m=2026-08')
    expect(rememberedView('classic', 'pnl')).toBe('?y=2025&q=%D0%B0%D1%80%D0%B5%D0%BD%D0%B4%D0%B0')
    expect(rememberedView('professional', 'cashflow')).toBe('')
  })

  it('forgets a card that is back on its defaults', () => {
    rememberView('professional', 'pnl', '?p=month')
    rememberView('professional', 'pnl', '')
    expect(rememberedView('professional', 'pnl')).toBe('')
  })

  it('ignores a stored value that is not a query string', () => {
    sessionStorage.setItem('reports.view.classic.cashflow', 'javascript:alert(1)')
    expect(rememberedView('classic', 'cashflow')).toBe('')
  })

  it('drops transient parameters from a query', () => {
    expect(viewToRemember('?line=rev&u=k', ['line'])).toBe('?u=k')
    expect(viewToRemember('?line=rev', ['line'])).toBe('')
  })

  it('works when the browser refuses session storage', async () => {
    await withoutSessionStorage(() => {
      expect(() => rememberView('classic', 'pnl', '?y=2025')).not.toThrow()
      expect(rememberedView('classic', 'pnl')).toBe('')
    })
  })
})
