import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { InvestmentsTab } from './InvestmentsTab'

const getInvestmentFundingConfigMock = vi.fn()

vi.mock('../../lib/api', () => ({
  getInvestmentFundingConfig: (...args: unknown[]) => getInvestmentFundingConfigMock(...args),
  createProjectInvestment: vi.fn(),
  getFundingPool: vi.fn(),
  createInvestmentsFromRequests: vi.fn(),
}))

vi.mock('../admin/AdminEditRecordButton', () => ({ AdminEditRecordButton: () => null }))

function renderTab() {
  return render(
    <MemoryRouter>
      <InvestmentsTab
        loading={false}
        rows={[]}
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
