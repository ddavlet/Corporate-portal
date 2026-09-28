import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const getStatementVendorsMock = vi.fn()
vi.mock('../../../../lib/reportsApi', () => ({
  getStatementVendors: (...args: unknown[]) => getStatementVendorsMock(...args),
}))

import { TopVendorsWidget } from './TopVendorsWidget'

const VENDORS = {
  total: '1140000.00',
  count: 2,
  items: [
    { vendor: 'ООО Офис', amount: '790000.00', requests: 2, line_id: 'opex.22222222', line_label: 'Аренда' },
    { vendor: 'ООО Поставщик', amount: '350000.00', requests: 3, line_id: 'opex.11111111', line_label: 'Маркетинг' },
  ],
}

function renderWidget(onOpenVendor = vi.fn()) {
  render(
    <TopVendorsWidget template="professional" report="pnl" from="2026-08-01" to="2026-08-31" units="m" onOpenVendor={onOpenVendor} />,
  )
  return onOpenVendor
}

describe('TopVendorsWidget', () => {
  // A block body: mockReset() returns the mock, and Vitest would run a returned function as a cleanup hook.
  beforeEach(() => {
    getStatementVendorsMock.mockReset()
  })

  it('lists the vendors of the period and opens one', async () => {
    getStatementVendorsMock.mockResolvedValue(VENDORS)
    const onOpenVendor = renderWidget()
    fireEvent.click(await screen.findByRole('button', { name: /ООО Офис/ }))
    expect(onOpenVendor).toHaveBeenCalledWith('ООО Офис')
    expect(screen.getByText('2 заявки · Аренда')).toBeInTheDocument()
    expect(getStatementVendorsMock).toHaveBeenCalledWith(
      { template: 'professional', report: 'pnl', from: '2026-08-01', to: '2026-08-31', limit: 6 },
      expect.anything(),
    )
  })

  it('offers a retry when loading fails', async () => {
    getStatementVendorsMock.mockRejectedValueOnce(new TypeError('Failed to fetch')).mockResolvedValue(VENDORS)
    renderWidget()
    fireEvent.click(await screen.findByRole('button', { name: 'Повторить' }))
    expect(await screen.findByRole('button', { name: /ООО Офис/ })).toBeInTheDocument()
    await waitFor(() => expect(getStatementVendorsMock).toHaveBeenCalledTimes(2))
  })

  it('says so when no request names a vendor', async () => {
    getStatementVendorsMock.mockResolvedValue({ total: '0.00', count: 0, items: [] })
    renderWidget()
    expect(await screen.findByText('За период нет заявок с поставщиком.')).toBeInTheDocument()
  })
})
