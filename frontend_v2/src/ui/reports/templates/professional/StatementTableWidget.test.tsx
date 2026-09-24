import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { StatementTableWidget } from './StatementTableWidget'
import { STATEMENT } from './testStatement'

function renderTable(overrides: { onDrill?: () => void; onToggle?: () => void } = {}) {
  const onDrill = overrides.onDrill ?? vi.fn()
  const onToggle = overrides.onToggle ?? vi.fn()
  render(
    <StatementTableWidget statement={STATEMENT} units="m" open={new Set(['rev', 'opex'])} selected={null} onToggle={onToggle} onDrill={onDrill} />,
  )
  return { onDrill, onToggle }
}

describe('StatementTableWidget', () => {
  it('opens the drill-down for the clicked line and period', () => {
    const { onDrill } = renderTable()
    fireEvent.click(screen.getByRole('button', { name: 'Банк: Авг' }))
    expect(onDrill).toHaveBeenCalledWith('rev.bank', STATEMENT.columns[0])
  })

  it('does not make results and margins clickable', () => {
    renderTable()
    expect(screen.queryByRole('button', { name: /^EBIT:/ })).toBeNull()
    expect(screen.queryByRole('button', { name: /^маржа EBIT:/ })).toBeNull()
  })

  it('collapses a section from its header', () => {
    const { onToggle } = renderTable()
    fireEvent.click(screen.getByRole('button', { name: 'Свернуть: Выручка' }))
    expect(onToggle).toHaveBeenCalledWith('rev')
  })

  it('shows «Итого» rows and colours expense growth as bad', () => {
    const { container } = render(
      <StatementTableWidget statement={STATEMENT} units="m" open={new Set(['rev', 'opex'])} selected={null} onToggle={vi.fn()} onDrill={vi.fn()} />,
    )
    expect(screen.getByText('Итого операционные расходы')).toBeInTheDocument()
    const expenseDeltas = container.querySelectorAll('.rp-row--total .rp-delta.rp-bad')
    expect(expenseDeltas.length).toBeGreaterThan(0)
  })

  it('shows only the given columns in the compact phone table', () => {
    render(
      <StatementTableWidget
        statement={STATEMENT}
        units="m"
        open={new Set(['rev', 'opex'])}
        selected={null}
        onToggle={vi.fn()}
        onDrill={vi.fn()}
        columnKeys={new Set(['2026-08', 'total'])}
        compact
      />,
    )
    expect(screen.getByRole('button', { name: 'Банк: Авг' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Банк: Сен* 1–23' })).toBeNull()
    expect(screen.queryByText('Год назад')).toBeNull()
  })
})
