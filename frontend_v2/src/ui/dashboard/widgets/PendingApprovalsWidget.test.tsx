import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { PendingApprovalsWidget } from './PendingApprovalsWidget'
import type { PendingApprovalItem } from './types'

function makeItem(overrides: Partial<PendingApprovalItem> = {}): PendingApprovalItem {
  return {
    approvalId: 1,
    requestId: 1,
    title: 'Заявка на оплату',
    description: null,
    amountText: '1 000',
    currency: 'UZS',
    step: 1,
    stepType: 'serial',
    ...overrides,
  }
}

describe('PendingApprovalsWidget', () => {
  it('shows the request description when present', () => {
    render(
      <PendingApprovalsWidget
        items={[makeItem({ description: 'Оплата аренды офиса за июль' })]}
        onApprove={vi.fn()}
        onReject={vi.fn()}
        onPayout={vi.fn()}
      />
    )
    expect(screen.getByText('Оплата аренды офиса за июль')).toBeInTheDocument()
  })

  it('does not render an extra description row when description is empty', () => {
    render(
      <PendingApprovalsWidget
        items={[makeItem({ description: '' })]}
        onApprove={vi.fn()}
        onReject={vi.fn()}
        onPayout={vi.fn()}
      />
    )
    expect(screen.queryByText('Оплата аренды офиса за июль')).not.toBeInTheDocument()
  })

  it('does not render an extra description row when description is whitespace-only', () => {
    const { container } = render(
      <PendingApprovalsWidget
        items={[makeItem({ description: '   ' })]}
        onApprove={vi.fn()}
        onReject={vi.fn()}
        onPayout={vi.fn()}
      />
    )
    // Without a description row, exactly 3 Typography.Text nodes render: title, amount, step.
    expect(container.querySelectorAll('.ant-typography')).toHaveLength(3)
  })
})
