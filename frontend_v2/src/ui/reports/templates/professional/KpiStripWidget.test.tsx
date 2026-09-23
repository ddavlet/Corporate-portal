import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
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
})
