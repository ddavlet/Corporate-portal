import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const useTenantAdminMock = vi.fn()
vi.mock('../../lib/useTenantAdmin', () => ({ useTenantAdmin: () => useTenantAdminMock() }))
vi.mock('../reports/rules/ReportRulesForm', async () => {
  const { createElement } = await import('react')
  return { ReportRulesForm: ({ report }: { report: string }) => createElement('div', null, `form:${report}`) }
})

import { ReportRulesSettingsPage } from './ReportRulesSettingsPage'

describe('ReportRulesSettingsPage', () => {
  beforeEach(() => {
    useTenantAdminMock.mockReturnValue({ isAdmin: true, loading: false })
  })

  it('shows the rules form of its report to admins', () => {
    render(<ReportRulesSettingsPage report="cashflow" />)
    expect(screen.getByText('Правила отчёта: Движение денег (Cashflow)')).toBeInTheDocument()
    expect(screen.getByText('form:cashflow')).toBeInTheDocument()
  })

  it('is closed to other users', () => {
    useTenantAdminMock.mockReturnValue({ isAdmin: false, loading: false })
    render(<ReportRulesSettingsPage report="pnl" />)
    expect(screen.getByText('Правила отчёта меняет администратор компании.')).toBeInTheDocument()
    expect(screen.queryByText('form:pnl')).toBeNull()
  })
})
