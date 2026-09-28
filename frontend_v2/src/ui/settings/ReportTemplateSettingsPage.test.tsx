import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const getReportTemplatesMock = vi.fn()
const updateReportTemplatesMock = vi.fn()
vi.mock('../../lib/reportsApi', () => ({
  getReportTemplates: () => getReportTemplatesMock(),
  updateReportTemplates: (...args: unknown[]) => updateReportTemplatesMock(...args),
}))
vi.mock('../../lib/apiNotify', () => ({ notifyApiSuccess: vi.fn() }))
const useTenantAdminMock = vi.fn()
vi.mock('../../lib/useTenantAdmin', () => ({ useTenantAdmin: () => useTenantAdminMock() }))

import { ReportTemplateSettingsPage } from './ReportTemplateSettingsPage'

const classic = { key: 'classic', label: 'Классический', description: 'Текущая страница', reports: ['pnl', 'cashflow'], engine: 'legacy' }
const professional = { key: 'professional', label: 'Профессиональный', description: 'Новый дизайн', reports: ['pnl', 'cashflow'], engine: 'statement' }

describe('ReportTemplateSettingsPage', () => {
  beforeEach(() => {
    useTenantAdminMock.mockReturnValue({ isAdmin: true, loading: false })
    getReportTemplatesMock.mockResolvedValue({ default: 'professional', allowed: [classic, professional], available: [classic, professional] })
    updateReportTemplatesMock.mockResolvedValue({ default: 'classic', allowed: [classic], available: [classic, professional] })
  })

  it('is closed to non-admins', async () => {
    useTenantAdminMock.mockReturnValue({ isAdmin: false, loading: false })
    render(<ReportTemplateSettingsPage />)
    expect(await screen.findByText('Шаблоны отчётов меняет администратор компании.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Сохранить' })).toBeNull()
  })

  it('moves the default when its template is no longer allowed and saves', async () => {
    render(<ReportTemplateSettingsPage />)
    const professionalBox = await screen.findByRole('checkbox', { name: /Профессиональный/ })
    fireEvent.click(professionalBox)
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }))
    await waitFor(() =>
      expect(updateReportTemplatesMock).toHaveBeenCalledWith({ default_template: 'classic', allowed_templates: ['classic'] }),
    )
  })
})
