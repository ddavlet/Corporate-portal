import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import type { StructuredReportPayload, StructuredReportRow } from '../../../../lib/api'

const row = (id: string, section: StructuredReportRow['section'], category: string, purpose: string): StructuredReportRow => ({
  id,
  date: '2026-08-05T00:00:00',
  amount: '100.00',
  direction: section === 'revenue' ? 'revenue' : 'expense',
  section,
  category,
  purpose,
  description: '',
  channel: '',
  raw: {},
})

const PAYLOAD = {
  report: 'pnl',
  metadata: {},
  totals: { revenue: '100', expense: '200', net: '-100' },
  monthly: [],
  rows: [
    row('1', 'revenue', 'Продажи', 'Поступление от клиента'),
    row('2', 'operational', 'Аренда', 'Аренда офиса за август'),
    row('3', 'other', 'Налоги', 'Налог НДС за август'),
  ],
  revenue: [],
  operational_expenses: [],
  other_expenses: [],
} as unknown as StructuredReportPayload

vi.mock('../../../../lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../../lib/api')>()
  return {
    ...actual,
    getStructuredPnlReport: vi.fn().mockResolvedValue(PAYLOAD),
    getStructuredCashflowReport: vi.fn().mockResolvedValue({ ...PAYLOAD, report: 'cashflow' }),
  }
})

import { ClassicReportTemplate } from './ClassicReportTemplate'

describe('ClassicReportTemplate', () => {
  it('opens only operational expenses from «Итого операционные расходы»', async () => {
    // The page scrolls the operations card into view; jsdom has no layout, so the call is a no-op here.
    Object.defineProperty(Element.prototype, 'scrollIntoView', { value: vi.fn(), configurable: true })
    render(
      <MemoryRouter>
        <ClassicReportTemplate templateSwitcher={null} />
      </MemoryRouter>,
    )
    fireEvent.click(await screen.findByText('Итого операционные расходы'))
    expect(await screen.findByText('Фильтр: Операционные расходы')).toBeInTheDocument()
    expect(screen.getByText('Аренда офиса за август')).toBeInTheDocument()
    expect(screen.queryByText('Налог НДС за август')).toBeNull()
    expect(screen.queryByText('Поступление от клиента')).toBeNull()
  })
})
