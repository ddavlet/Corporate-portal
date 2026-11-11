import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { InvestmentFormConfigPage } from './InvestmentFormConfigPage'

const getFormConfigMock = vi.fn()
const updateFormConfigMock = vi.fn()

vi.mock('../../lib/api', () => ({
  getInvestmentFormConfig: (...a: unknown[]) => getFormConfigMock(...a),
  updateInvestmentFormConfig: (...a: unknown[]) => updateFormConfigMock(...a),
}))

const CONFIG = {
  allowed_return_types: ['дивиденды'],
  return_type_choices: [
    { value: 'дивиденды', label: 'Дивиденды' },
    { value: 'проценты', label: 'Проценты' },
  ],
}

function renderPage() {
  return render(
    <MemoryRouter>
      <InvestmentFormConfigPage />
    </MemoryRouter>,
  )
}

describe('InvestmentFormConfigPage', () => {
  beforeEach(() => {
    getFormConfigMock.mockReset()
    updateFormConfigMock.mockReset()
    getFormConfigMock.mockResolvedValue(CONFIG)
  })

  it('has no "uses companies" switch', async () => {
    renderPage()
    expect(await screen.findByRole('checkbox', { name: 'Дивиденды' })).toBeChecked()
    expect(screen.queryByRole('switch')).not.toBeInTheDocument()
    expect(screen.queryByText(/компани/i)).not.toBeInTheDocument()
  })

  it('saves only the allowed return types', async () => {
    updateFormConfigMock.mockResolvedValue({ ...CONFIG, allowed_return_types: ['дивиденды', 'проценты'] })
    renderPage()

    fireEvent.click(await screen.findByRole('checkbox', { name: 'Проценты' }))
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }))

    await waitFor(() => expect(updateFormConfigMock).toHaveBeenCalledTimes(1))
    expect(updateFormConfigMock).toHaveBeenCalledWith({ allowed_return_types: ['дивиденды', 'проценты'] })
  })
})
