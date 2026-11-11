import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { TgInvestmentsPage } from './TgInvestmentsPage'

describe('TgInvestmentsPage', () => {
  it('shows the investment sections without a "Компании" tile', () => {
    render(
      <MemoryRouter>
        <TgInvestmentsPage />
      </MemoryRouter>,
    )
    expect(screen.getByRole('button', { name: /Заявки на вложение/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Расписание/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Выплаты/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Компании/ })).not.toBeInTheDocument()
  })
})
