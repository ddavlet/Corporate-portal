import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { STATEMENT } from './testStatement'
import { WaterfallWidget } from './WaterfallWidget'

describe('WaterfallWidget', () => {
  it('opens the operations of an expense bar', () => {
    const onDrill = vi.fn()
    render(<WaterfallWidget statement={STATEMENT} column={STATEMENT.columns[2]} units="m" onDrill={onDrill} />)
    fireEvent.click(screen.getByRole('button', { name: /Маркетинг/ }))
    expect(onDrill).toHaveBeenCalledWith('opex.11111111')
    // Result bars only explain the sum; they open nothing.
    expect(screen.queryByRole('button', { name: /EBIT/ })).toBeNull()
  })

  it('says so when the period has no money', () => {
    const empty = { ...STATEMENT, rows: STATEMENT.rows.map((row) => ({ ...row, values: {} })) }
    render(<WaterfallWidget statement={empty} column={STATEMENT.columns[2]} units="m" onDrill={vi.fn()} />)
    expect(screen.getByText('Нет данных за период.')).toBeInTheDocument()
  })

  it('keeps the bar buttons reachable for screen readers', () => {
    render(<WaterfallWidget statement={STATEMENT} column={STATEMENT.columns[2]} units="m" onDrill={vi.fn()} />)
    expect(screen.getByRole('group', { name: 'От выручки к прибыли' })).toContainElement(screen.getByRole('button', { name: /Маркетинг/ }))
  })

  it('shows long line names in full', () => {
    const statement = {
      ...STATEMENT,
      rows: STATEMENT.rows.map((row) => (row.id === 'opex.11111111' ? { ...row, label: 'Хозяйственные расходы офиса' } : row)),
    }
    render(<WaterfallWidget statement={statement} column={STATEMENT.columns[2]} units="m" onDrill={vi.fn()} />)
    const axis = [...document.querySelectorAll('.rp-wf-label tspan')].map((line) => line.textContent)
    expect(axis).toEqual(expect.arrayContaining(['Хозяйственные', 'расходы офиса']))
  })
})
