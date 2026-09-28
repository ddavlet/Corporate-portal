import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { StatementResponse } from '../../../../lib/reportsApi'
import { SummaryHeroWidget } from './SummaryHeroWidget'
import { STATEMENT } from './testStatement'

const WITH_NET: StatementResponse = {
  ...STATEMENT,
  kpis: [
    ...STATEMENT.kpis,
    {
      id: 'net',
      label: 'Чистая прибыль',
      polarity: 'result',
      value: '-1300000.00',
      ratio: '-0.0600',
      comparisons: [{ key: 'yoy', label: 'к авг – 23 сен 2025', value: '100000.00', delta_pct: '-2.5000' }],
      spark: [],
    },
  ],
}

describe('SummaryHeroWidget', () => {
  it('shows the headline number, how it compares and what it is made of', () => {
    render(<SummaryHeroWidget statement={WITH_NET} column={STATEMENT.columns[2]} units="m" />)
    expect(screen.getByText('−1,3')).toHaveClass('rp-neg')
    expect(screen.getByText('маржа −6,0%')).toBeInTheDocument()
    expect(screen.getByText('−250,0% к авг – 23 сен 2025')).toHaveClass('rp-chip--bad')
    expect(screen.getByText(/Больше всего потрачено на маркетинг/)).toBeInTheDocument()
  })

  it('stays out of the way when the report has no headline number', () => {
    const { container } = render(<SummaryHeroWidget statement={STATEMENT} column={STATEMENT.columns[2]} units="m" />)
    expect(container).toBeEmptyDOMElement()
  })
})
