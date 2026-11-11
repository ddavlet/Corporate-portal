import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { PublicInvestmentsSchedulePage } from './PublicInvestmentsSchedulePage'

const getPublicScheduleMock = vi.fn()

vi.mock('../lib/api', () => ({
  getPublicInvestPayoutSchedule: (...a: unknown[]) => getPublicScheduleMock(...a),
}))

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/public/investments/schedule/tok123']}>
      <Routes>
        <Route path="/public/investments/schedule/:token" element={<PublicInvestmentsSchedulePage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('PublicInvestmentsSchedulePage', () => {
  beforeEach(() => {
    getPublicScheduleMock.mockReset()
  })

  it('titles the schedule with the tenant name and shows no company column', async () => {
    getPublicScheduleMock.mockResolvedValue({
      filters: { tenant_name: 'Lemon Fit', paid_filter: 'all' },
      rows: [
        {
          id: 7,
          payout_date: '2026-12-01',
          amount: '1500',
          is_paid: false,
          payment_amount: '0',
          comment: 'Дивиденды за ноябрь',
          currency: 'USD',
        },
      ],
    })
    renderPage()

    expect(await screen.findByRole('heading', { name: 'Lemon Fit' })).toBeInTheDocument()
    expect(getPublicScheduleMock).toHaveBeenCalledWith('tok123')
    expect(screen.getByText('Дивиденды за ноябрь')).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'Сумма' })).toBeInTheDocument()
    expect(screen.queryByRole('columnheader', { name: 'Компания' })).not.toBeInTheDocument()
    expect(screen.queryByText('Без компании')).not.toBeInTheDocument()
  })

  it('shows a dash when the tenant name is empty', async () => {
    getPublicScheduleMock.mockResolvedValue({ filters: { tenant_name: '', paid_filter: 'all' }, rows: [] })
    renderPage()
    expect(await screen.findByRole('heading', { name: '—' })).toBeInTheDocument()
  })
})
