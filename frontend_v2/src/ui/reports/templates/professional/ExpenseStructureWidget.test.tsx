import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ExpenseStructureWidget } from './ExpenseStructureWidget'
import { STATEMENT } from './testStatement'

describe('ExpenseStructureWidget', () => {
  it('opens the operations of a line from the legend', () => {
    const onDrill = vi.fn()
    render(<ExpenseStructureWidget statement={STATEMENT} column={STATEMENT.columns[2]} units="m" onDrill={onDrill} />)
    fireEvent.click(screen.getByRole('button', { name: /Маркетинг/ }))
    expect(onDrill).toHaveBeenCalledWith('opex.11111111')
  })

  it('says so when there are no expenses', () => {
    const statement = { ...STATEMENT, rows: STATEMENT.rows.filter((row) => !row.id.startsWith('opex')) }
    render(<ExpenseStructureWidget statement={statement} column={STATEMENT.columns[2]} units="m" onDrill={vi.fn()} />)
    expect(screen.getByText('Расходов за период нет.')).toBeInTheDocument()
  })
})
