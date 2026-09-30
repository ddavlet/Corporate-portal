import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { ReportCard } from '../reportCards'

// Stub form: shows its report and saves on click. createElement, not JSX: this factory is hoisted above the imports.
vi.mock('./ReportRulesForm', async () => {
  const { createElement } = await import('react')
  return {
    ReportRulesForm: ({ report, onSaved }: { report: string; onSaved?: () => void }) =>
      createElement('button', { type: 'button', onClick: () => onSaved?.() }, `form:${report}`),
  }
})

import { ReportRulesDrawer } from './ReportRulesDrawer'

const card = (template: string, report: 'pnl' | 'cashflow', title: string): ReportCard => ({
  template,
  templateLabel: template,
  report,
  title,
  description: '',
  path: `/reports/${template}/${report}`,
})

const CARDS = [
  card('professional', 'pnl', 'Прибыли и убытки'),
  card('professional', 'cashflow', 'Движение денег'),
  card('classic', 'pnl', 'PnL'),
  card('classic', 'cashflow', 'Cashflow'),
]

describe('ReportRulesDrawer', () => {
  it('shows the rules of the report and the cards that share them', async () => {
    render(<ReportRulesDrawer report="pnl" cards={CARDS} onClose={vi.fn()} />)
    expect(await screen.findByText('Правила отчёта: Прибыли и убытки (PnL)')).toBeInTheDocument()
    expect(screen.getByText('Эти правила используют карточки «Прибыли и убытки» и «PnL».')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'form:pnl' })).toBeInTheDocument()
  })

  it('names a single card in the singular', async () => {
    render(<ReportRulesDrawer report="cashflow" cards={CARDS.filter((c) => c.template === 'classic')} onClose={vi.fn()} />)
    expect(await screen.findByText('Эти правила использует карточка «Cashflow».')).toBeInTheDocument()
  })

  it('stays closed without a report', () => {
    render(<ReportRulesDrawer report={null} cards={CARDS} onClose={vi.fn()} />)
    expect(screen.queryByText(/Правила отчёта/)).toBeNull()
  })

  it('passes a save on and closes when asked', async () => {
    const onSaved = vi.fn()
    const onClose = vi.fn()
    render(<ReportRulesDrawer report="cashflow" cards={CARDS} onClose={onClose} onSaved={onSaved} />)
    fireEvent.click(await screen.findByRole('button', { name: 'form:cashflow' }))
    expect(onSaved).toHaveBeenCalledTimes(1)
    fireEvent.click(screen.getByRole('button', { name: 'Close' }))
    expect(onClose).toHaveBeenCalledTimes(1)
  })
})
