import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReportTemplateInfo } from '../../lib/reportsApi'
import { withoutSessionStorage } from '../../test/helpers'

const useReportTemplatesMock = vi.fn()
vi.mock('../../lib/useReportTemplates', () => ({ useReportTemplates: () => useReportTemplatesMock() }))
const useTenantAdminMock = vi.fn()
vi.mock('../../lib/useTenantAdmin', () => ({ useTenantAdmin: () => useTenantAdminMock() }))
// Stub drawer: shows which report's rules are open. createElement, not JSX: this factory is hoisted above the imports.
vi.mock('./rules/ReportRulesDrawer', async () => {
  const { createElement } = await import('react')
  return {
    ReportRulesDrawer: ({ report }: { report: string | null }) => (report ? createElement('div', null, `rules:${report}`) : null),
  }
})

import { ReportsPage } from './ReportsPage'

const info = (key: string, label: string): ReportTemplateInfo => ({
  key,
  label,
  description: '',
  reports: ['pnl', 'cashflow'],
  engine: key === 'classic' ? 'legacy' : 'statement',
})
const classic = info('classic', 'Классический')
const professional = info('professional', 'Профессиональный')
const loaded = (defaultKey: string, allowed: ReportTemplateInfo[]) => ({
  templates: { default: defaultKey, allowed, available: [classic, professional] },
  failed: false,
  loading: false,
})

function Location() {
  const { pathname, search } = useLocation()
  return <output data-testid="location">{`${pathname}${search}`}</output>
}

function renderAt(url: string) {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route path="/reports" element={<ReportsPage />} />
        <Route path="/reports/:template/:report" element={<Location />} />
      </Routes>
    </MemoryRouter>,
  )
}

const cardTitles = () => screen.getAllByRole('link').map((link) => link.textContent)

describe('ReportsPage', () => {
  const fetchMock = vi.fn()

  beforeEach(() => {
    sessionStorage.clear()
    useTenantAdminMock.mockReturnValue({ isAdmin: false, loading: false })
    useReportTemplatesMock.mockReturnValue(loaded('professional', [classic, professional]))
    Object.defineProperty(globalThis, 'fetch', { value: fetchMock, configurable: true })
  })

  it('shows a card for every report of every allowed template, the «show first» template first', () => {
    renderAt('/reports')
    expect(cardTitles()).toEqual(['Прибыли и убытки', 'Движение денег', 'PnL', 'Cashflow'])
  })

  it('hides the cards of a template the company has not allowed', () => {
    useReportTemplatesMock.mockReturnValue(loaded('classic', [classic]))
    renderAt('/reports')
    expect(cardTitles()).toEqual(['PnL', 'Cashflow'])
  })

  it('shows the Classic cards when the template list cannot be loaded', () => {
    useReportTemplatesMock.mockReturnValue({ templates: null, failed: true, loading: false })
    renderAt('/reports')
    expect(cardTitles()).toEqual(['PnL', 'Cashflow'])
  })

  it('loads no report data', () => {
    renderAt('/reports')
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('opens a card with the view it was left in', () => {
    sessionStorage.setItem('reports.view.professional.cashflow', '?p=month&m=2026-08')
    renderAt('/reports')
    const link = screen.getByRole('link', { name: 'Движение денег' })
    expect(link).toHaveAttribute('href', '/reports/professional/cashflow?p=month&m=2026-08')
    fireEvent.click(link)
    expect(screen.getByTestId('location')).toHaveTextContent('/reports/professional/cashflow?p=month&m=2026-08')
  })

  it('opens the cards with their defaults when the browser refuses session storage', async () => {
    await withoutSessionStorage(() => {
      renderAt('/reports')
      expect(screen.getByRole('link', { name: 'Движение денег' })).toHaveAttribute('href', '/reports/professional/cashflow')
    })
  })

  it('leaves Ctrl, Cmd and Shift clicks on a card to the browser instead of opening the report here', () => {
    renderAt('/reports')
    const body = screen.getByText('Показатели, график и отчёт о движении денег с остатками и сравнением.')
    for (const modifier of [{ ctrlKey: true }, { metaKey: true }, { shiftKey: true }]) {
      fireEvent.click(body, modifier)
      expect(screen.queryByTestId('location')).toBeNull()
    }
  })

  it('opens the rules of a report for admins without leaving the cards', () => {
    useTenantAdminMock.mockReturnValue({ isAdmin: true, loading: false })
    renderAt('/reports')
    fireEvent.click(screen.getByRole('button', { name: 'Правила отчёта «PnL»' }))
    expect(screen.getByText('rules:pnl')).toBeInTheDocument()
    expect(screen.queryByTestId('location')).toBeNull()
  })

  it('offers no rules to other users', () => {
    renderAt('/reports')
    expect(screen.queryByRole('button', { name: /Правила отчёта/ })).toBeNull()
  })

  it('sends a link from before the cards to the card of its report', () => {
    useReportTemplatesMock.mockReturnValue(loaded('classic', [classic, professional]))
    renderAt('/reports?t=professional&r=cashflow&p=month&line=rev.bank&from=2026-08-01&to=2026-08-31')
    expect(screen.getByTestId('location')).toHaveTextContent(
      '/reports/professional/cashflow?p=month&line=rev.bank&from=2026-08-01&to=2026-08-31',
    )
  })

  it('sends a link copied from the old address bar, without `t` and `r`, to the template it was made in', () => {
    useReportTemplatesMock.mockReturnValue(loaded('classic', [classic, professional]))
    renderAt('/reports?p=month&m=2026-08&line=rev.bank')
    expect(screen.getByTestId('location')).toHaveTextContent('/reports/professional/pnl?p=month&m=2026-08&line=rev.bank')
  })
})
