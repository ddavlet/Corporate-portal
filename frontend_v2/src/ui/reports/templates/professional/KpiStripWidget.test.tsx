import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { KpiStripWidget } from './KpiStripWidget'
import { STATEMENT } from './testStatement'

describe('KpiStripWidget', () => {
  it('shows the value in units and the change against last year', () => {
    render(<KpiStripWidget kpis={STATEMENT.kpis} units="m" />)
    expect(screen.getByText('Выручка')).toBeInTheDocument()
    expect(screen.getByText('2,5')).toBeInTheDocument()
    expect(screen.getByText('+212,5%')).toBeInTheDocument()
    expect(screen.getByText('к авг – 23 сен 2025')).toBeInTheDocument()
  })

  it('opens a tile that stands for one row and leaves the others still', () => {
    const onOpen = vi.fn()
    const kpis = [...STATEMENT.kpis, { ...STATEMENT.kpis[0], id: 'out', label: 'Выплаты' }]
    render(<KpiStripWidget kpis={kpis} units="m" openable={new Set(['rev'])} onOpen={onOpen} />)
    fireEvent.click(screen.getByRole('button', { name: /Выручка/ }))
    expect(onOpen).toHaveBeenCalledWith('rev')
    expect(screen.queryByRole('button', { name: /Выплаты/ })).toBeNull()
  })

  it('leaves out the number shown in the summary card', () => {
    render(<KpiStripWidget kpis={STATEMENT.kpis} units="m" exclude="rev" />)
    expect(screen.queryByText('Выручка')).toBeNull()
  })
})
