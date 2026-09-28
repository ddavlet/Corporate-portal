import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { StatementChart } from '../../../../lib/reportsApi'
import { STATEMENT } from './testStatement'
import { TrendChartWidget } from './TrendChartWidget'

const MONTHLY: StatementChart = { ...STATEMENT.chart, months: [['2026-08'], ['2026-09']] }

function renderChart(chart: StatementChart = MONTHLY, onFocusMonth = vi.fn()) {
  render(<TrendChartWidget chart={chart} units="m" report="pnl" collapsed={false} onToggle={vi.fn()} onFocusMonth={onFocusMonth} />)
  return onFocusMonth
}

describe('TrendChartWidget', () => {
  it('switches the report to the month of a bar', () => {
    const onFocusMonth = renderChart()
    fireEvent.click(screen.getByRole('button', { name: 'Авг: показать месяц' }))
    expect(onFocusMonth).toHaveBeenCalledWith('2026-08')
  })

  it('shows the numbers of the month under the pointer', () => {
    renderChart()
    fireEvent.mouseEnter(screen.getByRole('button', { name: 'Авг: показать месяц' }))
    const tip = (document.querySelector('.rp-chart-tip')?.textContent ?? '').replace(/[  ]/g, ' ')
    expect(tip).toContain('Выручка1,8 млн')
    expect(tip).toContain('Чистая прибыль1,5 млн')
    expect(tip).toContain('Маржа80,6%')
  })

  it('keeps quarter bars unclickable', () => {
    renderChart({ ...STATEMENT.chart, months: [['2026-07', '2026-08', '2026-09'], ['2026-10', '2026-11', '2026-12']] })
    expect(screen.queryAllByRole('button', { name: /показать месяц/ })).toHaveLength(0)
  })

  it('keeps an old answer without month keys unclickable', () => {
    renderChart(STATEMENT.chart)
    expect(screen.queryAllByRole('button', { name: /показать месяц/ })).toHaveLength(0)
  })

  it('keeps the month buttons reachable for screen readers', () => {
    renderChart()
    // An «img» would hide its buttons from assistive technology; a labelled group keeps them.
    expect(screen.getByRole('group', { name: /столбцами/ })).toContainElement(screen.getByRole('button', { name: 'Авг: показать месяц' }))
  })
})
