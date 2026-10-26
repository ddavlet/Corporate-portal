import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { ProjectInvestmentRow } from '../../lib/api'
import { InvestmentsTab } from './InvestmentsTab'
import { asMoney } from './utils'

const getInvestmentFundingConfigMock = vi.fn()

vi.mock('../../lib/api', () => ({
  getInvestmentFundingConfig: (...args: unknown[]) => getInvestmentFundingConfigMock(...args),
  createProjectInvestment: vi.fn(),
  getFundingPool: vi.fn(),
  createInvestmentsFromRequests: vi.fn(),
}))

vi.mock('../admin/AdminEditRecordButton', () => ({ AdminEditRecordButton: () => null }))

function renderTab(rows: ProjectInvestmentRow[] = []) {
  return render(
    <MemoryRouter>
      <InvestmentsTab
        loading={false}
        rows={rows}
        companies={[]}
        companyLabel={() => '-'}
        companyFilter="all"
        usesCompanies={false}
        onCreated={() => {}}
      />
    </MemoryRouter>,
  )
}

describe('InvestmentsTab funding mode', () => {
  beforeEach(() => {
    getInvestmentFundingConfigMock.mockReset()
  })

  it('hides manual creation and shows "Собрать по заявкам" when the mode is on', async () => {
    getInvestmentFundingConfigMock.mockResolvedValue({ is_enabled: true })
    renderTab()
    await waitFor(() => expect(screen.getAllByRole('button', { name: 'Собрать по заявкам' }).length).toBeGreaterThan(0))
    expect(screen.queryByRole('button', { name: 'Подать заявку на вложение' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Подать первую заявку' })).toBeNull()
  })

  it('keeps manual creation when the mode is off', async () => {
    getInvestmentFundingConfigMock.mockResolvedValue({ is_enabled: false })
    renderTab()
    expect(await screen.findByRole('button', { name: 'Подать заявку на вложение' })).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Собрать по заявкам' })).toBeNull()
  })

  it('keeps manual creation when the config request fails', async () => {
    getInvestmentFundingConfigMock.mockRejectedValue(new Error('403'))
    renderTab()
    expect(await screen.findByRole('button', { name: 'Подать заявку на вложение' })).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Собрать по заявкам' })).toBeNull()
  })
})

function row(id: number, confirmed: boolean, sumUsd: number, sumUzs: number): ProjectInvestmentRow {
  return {
    id,
    company: null,
    date: '2026-10-20',
    amount: String(sumUzs),
    currency: 'UZS',
    sum_usd: String(sumUsd),
    sum_uzs: String(sumUzs),
    comment: '',
    confirmed,
    created_at: '2026-10-20T10:00:00Z',
  }
}

describe('InvestmentsTab totals', () => {
  beforeEach(() => {
    getInvestmentFundingConfigMock.mockReset()
    getInvestmentFundingConfigMock.mockResolvedValue({ is_enabled: false })
  })

  it('shows confirmed and unconfirmed totals separately', async () => {
    renderTab([row(1, true, 100, 1200000), row(2, true, 50, 600000), row(3, false, 10, 120000)])

    const confirmedUsd = await screen.findByText('Подтверждено, USD')
    expect(confirmedUsd.parentElement?.textContent).toContain(asMoney(150))
    expect(screen.getByText('Подтверждено, UZS').parentElement?.textContent).toContain(asMoney(1800000))
    expect(screen.getByText('Не подтверждено, USD').parentElement?.textContent).toContain(asMoney(10))
    expect(screen.getByText('Не подтверждено, UZS').parentElement?.textContent).toContain(asMoney(120000))
    expect(screen.queryByText('Не учтено в сумме')).toBeNull()
  })
})
