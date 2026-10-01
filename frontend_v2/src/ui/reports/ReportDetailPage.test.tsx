import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReportTemplateInfo } from '../../lib/reportsApi'
import { withoutSessionStorage } from '../../test/helpers'
import type { ReportTemplateProps } from './templates/types'

const useReportTemplatesMock = vi.fn()
vi.mock('../../lib/useReportTemplates', () => ({ useReportTemplates: () => useReportTemplatesMock() }))
const useTenantAdminMock = vi.fn()
vi.mock('../../lib/useTenantAdmin', () => ({ useTenantAdmin: () => useTenantAdminMock() }))
// Stubs: createElement, not JSX, because these factories are hoisted above the file's imports.
vi.mock('./rules/ReportRulesDrawer', async () => {
  const { createElement } = await import('react')
  return {
    ReportRulesDrawer: ({ report, onSaved }: { report: string | null; onSaved?: () => void }) =>
      report ? createElement('button', { type: 'button', onClick: () => onSaved?.() }, `save rules:${report}`) : null,
  }
})
vi.mock('./templates/registry', async () => {
  const { createElement } = await import('react')
  const view = (key: string) => async () => ({
    default: ({ report, onOpenRules, rulesVersion }: ReportTemplateProps) =>
      createElement('span', null, `view:${key}:${report}:${rulesVersion}:${onOpenRules ? 'rules' : 'no-rules'}`),
  })
  return {
    FALLBACK_TEMPLATE: 'classic',
    REPORT_TEMPLATE_REGISTRY: {
      classic: {
        key: 'classic',
        label: 'Классический',
        reports: { pnl: { title: 'PnL', description: '' }, cashflow: { title: 'Cashflow', description: '' } },
        load: view('classic'),
      },
      professional: {
        key: 'professional',
        label: 'Профессиональный',
        reports: {
          pnl: { title: 'Прибыли и убытки', description: '' },
          cashflow: { title: 'Движение денег', description: '' },
        },
        transientParams: ['line', 'from', 'to', 'vendor'],
        load: view('professional'),
      },
    },
  }
})

import { ReportDetailPage } from './ReportDetailPage'

const info = (key: string, label: string): ReportTemplateInfo => ({
  key,
  label,
  description: '',
  reports: ['pnl', 'cashflow'],
  engine: key === 'classic' ? 'legacy' : 'statement',
})
const classic = info('classic', 'Классический')
const professional = info('professional', 'Профессиональный')
const loaded = (allowed: ReportTemplateInfo[]) => ({
  templates: { default: 'classic', allowed, available: [classic, professional] },
  failed: false,
  loading: false,
})

function renderAt(url: string) {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route path="/reports/:template/:report" element={<ReportDetailPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('ReportDetailPage', () => {
  beforeEach(() => {
    sessionStorage.clear()
    useReportTemplatesMock.mockReturnValue(loaded([classic, professional]))
    useTenantAdminMock.mockReturnValue({ isAdmin: false, loading: false })
  })

  it('shows the report of the path in its template', async () => {
    renderAt('/reports/professional/cashflow')
    expect(await screen.findByText('view:professional:cashflow:0:no-rules')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Движение денег' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Все отчёты/ })).toHaveAttribute('href', '/reports')
  })

  it('says when there is no such report', () => {
    for (const url of ['/reports/professional/ghost', '/reports/classic/__proto__', '/reports/constructor/pnl']) {
      const { unmount } = renderAt(url)
      expect(screen.getByText('Отчёт не найден')).toBeInTheDocument()
      unmount()
    }
  })

  it('says when the company has not allowed the template', () => {
    useReportTemplatesMock.mockReturnValue(loaded([classic]))
    renderAt('/reports/professional/pnl')
    expect(screen.getByText('Шаблон «Профессиональный» недоступен')).toBeInTheDocument()
  })

  it('does not blame the administrator when the template list failed to load, and asks again', () => {
    const retry = vi.fn()
    useReportTemplatesMock.mockReturnValue({ templates: null, failed: true, loading: false, retry })
    renderAt('/reports/professional/pnl')
    expect(screen.getByText('Не удалось загрузить список шаблонов. Попробуйте ещё раз.')).toBeInTheDocument()
    expect(screen.queryByText('Администратор компании не включил этот шаблон.')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Повторить' }))
    expect(retry).toHaveBeenCalledTimes(1)
  })

  it('opens the rules for admins and reloads the report after a save', async () => {
    useTenantAdminMock.mockReturnValue({ isAdmin: true, loading: false })
    renderAt('/reports/classic/pnl')
    expect(await screen.findByText('view:classic:pnl:0:rules')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Правила отчёта «PnL»' }))
    fireEvent.click(screen.getByRole('button', { name: 'save rules:pnl' }))
    expect(await screen.findByText('view:classic:pnl:1:rules')).toBeInTheDocument()
  })

  it('shows the report when the browser refuses session storage', async () => {
    await withoutSessionStorage(async () => {
      renderAt('/reports/professional/pnl?p=month')
      expect(await screen.findByText('view:professional:pnl:0:no-rules')).toBeInTheDocument()
    })
  })

  it('remembers the view of the card without the open drill-down', async () => {
    renderAt('/reports/professional/pnl?p=month&m=2026-08&line=rev&from=2026-08-01&to=2026-08-31')
    await screen.findByText('view:professional:pnl:0:no-rules')
    expect(sessionStorage.getItem('reports.view.professional.pnl')).toBe('?p=month&m=2026-08')
  })
})
