import { render, screen, within } from '@testing-library/react'
import { theme } from 'antd'
import { describe, expect, it } from 'vitest'
import { contrastRatio } from '../../test/contrast'
import type { ApprovalItem } from './RequestDetailModal'
import { RequestApprovalsTimelineWidget } from './RequestApprovalsTimelineWidget'

const token = theme.getDesignToken()

function approval(overrides: Partial<ApprovalItem>): ApprovalItem {
  return {
    id: 1,
    step: 1,
    step_type: 'approval',
    decision: 'approved',
    approver_user: 3,
    approver_username: 'petrov',
    decided_at: '2026-11-10T09:00:00Z',
    ...overrides,
  }
}

/** The colour the decision line of an approval is written in. */
function decisionColor(id: number, text: RegExp): string {
  const line = screen.getByTestId(`approval-${id}-decision`)
  expect(line).toHaveTextContent(text)
  return line.style.color
}

describe('RequestApprovalsTimelineWidget', () => {
  it('tells a decided step, the active pending step and a step the queue has not reached apart', () => {
    render(
      <RequestApprovalsTimelineWidget
        activeApprovalStep={2}
        approvals={[
          approval({ id: 1, step: 1, decision: 'approved' }),
          approval({ id: 2, step: 2, decision: 'pending', decided_at: null }),
          approval({ id: 3, step: 3, step_type: 'payment', decision: 'pending', decided_at: null }),
        ]}
      />,
    )

    expect(screen.getByTestId('approval-1')).toHaveAttribute('data-state', 'decided')
    expect(screen.getByTestId('approval-2')).toHaveAttribute('data-state', 'pending')
    expect(within(screen.getByTestId('approval-2')).getByText('Ожидает')).toBeInTheDocument()

    const future = screen.getByTestId('approval-3')
    expect(future).toHaveAttribute('data-state', 'not-started')
    expect(within(future).getByText('Не начат')).toBeInTheDocument()
    expect(within(future).queryByText('Ожидает')).toBeNull()
    expect(screen.getByTestId('approval-3-decision')).toHaveStyle({ color: token.colorTextSecondary })
  })

  it('keeps every pending step «Ожидает» when the active step is unknown', () => {
    render(
      <RequestApprovalsTimelineWidget
        approvals={[
          approval({ id: 2, step: 2, decision: 'pending', decided_at: null }),
          approval({ id: 3, step: 3, decision: 'pending', decided_at: null }),
        ]}
      />,
    )

    expect(within(screen.getByTestId('approval-3')).getByText('Ожидает')).toBeInTheDocument()
    expect(screen.queryByText('Не начат')).toBeNull()
  })

  it('writes every decision at 4.5:1 or more on white', () => {
    render(
      <RequestApprovalsTimelineWidget
        activeApprovalStep={3}
        approvals={[
          approval({ id: 1, step: 1, decision: 'approved' }),
          approval({ id: 2, step: 2, decision: 'rejected', comment: 'Нет договора' }),
          approval({ id: 3, step: 3, decision: 'pending', decided_at: null }),
          approval({ id: 4, step: 4, decision: 'pending', decided_at: null }),
        ]}
      />,
    )

    const colors = [
      decisionColor(1, /Одобрено/),
      decisionColor(2, /Отклонено/),
      decisionColor(3, /Ожидает/),
      decisionColor(4, /Не начат/),
    ]
    expect(contrastRatio('#000000')).toBeCloseTo(21, 0)
    for (const color of colors) {
      expect(color).not.toBe('')
      expect(contrastRatio(color)).toBeGreaterThanOrEqual(4.5)
    }
  })
})
