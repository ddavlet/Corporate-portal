import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReportTemplateProps } from './templates/types'

const getReportTemplatesMock = vi.fn()
vi.mock('../../lib/reportsApi', () => ({ getReportTemplates: () => getReportTemplatesMock() }))

const setUserPreferenceMock = vi.fn()
vi.mock('../../lib/api', () => ({
  getUserPreferences: vi.fn().mockResolvedValue({}),
  setUserPreference: (...args: unknown[]) => setUserPreferenceMock(...args),
}))

// Stub templates: each renders its name and the switcher it was given. createElement, not JSX,
// because this factory is hoisted above the file's imports.
vi.mock('./templates/registry', async () => {
  const { createElement } = await import('react')
  const entry = (key: string, label: string) => ({
    key,
    label,
    supports: ['pnl', 'cashflow'],
    load: async () => ({
      default: ({ templateSwitcher }: ReportTemplateProps) =>
        createElement('div', null, createElement('span', null, `view:${key}`), templateSwitcher),
    }),
  })
  return {
    REPORT_TEMPLATE_REGISTRY: {
      classic: entry('classic', 'Классический'),
      professional: entry('professional', 'Профессиональный'),
    },
  }
})

import { ReportsPage } from './ReportsPage'

const info = (key: string, label: string) => ({ key, label, description: '', reports: ['pnl', 'cashflow'], engine: key === 'classic' ? 'legacy' : 'statement' })

function renderAt(url: string) {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <ReportsPage />
    </MemoryRouter>,
  )
}

describe('ReportsPage', () => {
  beforeEach(() => {
    getReportTemplatesMock.mockReset()
    setUserPreferenceMock.mockReset().mockResolvedValue(undefined)
  })

  it('hides the switcher when only one template is allowed', async () => {
    getReportTemplatesMock.mockResolvedValue({ default: 'classic', allowed: [info('classic', 'Классический')], available: [info('classic', 'Классический'), info('professional', 'Профессиональный')] })
    renderAt('/reports')
    expect(await screen.findByText('view:classic')).toBeInTheDocument()
    expect(screen.queryByText('Профессиональный')).toBeNull()
  })

  it('opens the tenant default and offers the switcher', async () => {
    const both = [info('classic', 'Классический'), info('professional', 'Профессиональный')]
    getReportTemplatesMock.mockResolvedValue({ default: 'professional', allowed: both, available: both })
    renderAt('/reports')
    expect(await screen.findByText('view:professional')).toBeInTheDocument()
    expect(screen.getByText('Классический')).toBeInTheDocument()
  })

  it('explains when the linked template is not available', async () => {
    getReportTemplatesMock.mockResolvedValue({ default: 'classic', allowed: [info('classic', 'Классический')], available: [info('classic', 'Классический'), info('professional', 'Профессиональный')] })
    renderAt('/reports?t=professional')
    expect(await screen.findByText('Шаблон «Профессиональный» недоступен, показан «Классический».')).toBeInTheDocument()
    expect(screen.getByText('view:classic')).toBeInTheDocument()
  })

  it('falls back to Classic when templates cannot be loaded', async () => {
    getReportTemplatesMock.mockRejectedValue(new Error('network'))
    renderAt('/reports')
    expect(await screen.findByText('view:classic')).toBeInTheDocument()
  })

  it('never saves the template preference as null', async () => {
    getReportTemplatesMock.mockResolvedValue({ default: 'classic', allowed: [info('classic', 'Классический')], available: [info('classic', 'Классический')] })
    renderAt('/reports')
    await screen.findByText('view:classic')
    await waitFor(() => expect(setUserPreferenceMock).toHaveBeenCalledWith('reports.template.v1', ''), { timeout: 2000 })
    expect(setUserPreferenceMock.mock.calls.some(([, value]) => value === null)).toBe(false)
  })
})
