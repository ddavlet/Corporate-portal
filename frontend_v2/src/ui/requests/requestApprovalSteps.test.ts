import { describe, expect, it } from 'vitest'
import type { ApprovalItem } from './RequestDetailModal'
import { isNotificationApprovalStep, isPaymentApprovalStep, minPendingApprovalStep } from './requestApprovalSteps'

function approval(overrides: Partial<ApprovalItem>): ApprovalItem {
  return { id: 1, step: 1, step_type: 'approval', decision: 'pending', ...overrides }
}

describe('requestApprovalSteps', () => {
  it('recognises payment steps whatever the case', () => {
    expect(isPaymentApprovalStep(approval({ step_type: 'payment' }))).toBe(true)
    expect(isPaymentApprovalStep(approval({ step_type: 'PAYMENT' }))).toBe(true)
    expect(isPaymentApprovalStep(approval({ step_type: 'approval' }))).toBe(false)
    expect(isPaymentApprovalStep(approval({ step_type: '' }))).toBe(false)
  })

  it('recognises notification steps whatever the case', () => {
    expect(isNotificationApprovalStep(approval({ step_type: 'notification' }))).toBe(true)
    expect(isNotificationApprovalStep(approval({ step_type: 'Notification' }))).toBe(true)
    expect(isNotificationApprovalStep(approval({ step_type: 'payment' }))).toBe(false)
  })

  it('finds the smallest step that still waits for a decision', () => {
    expect(minPendingApprovalStep(undefined)).toBeNull()
    expect(minPendingApprovalStep([])).toBeNull()
    expect(
      minPendingApprovalStep([
        approval({ id: 1, step: 1, decision: 'approved' }),
        approval({ id: 2, step: 3, decision: 'pending' }),
        approval({ id: 3, step: 2, decision: 'PENDING' }),
      ]),
    ).toBe(2)
    expect(
      minPendingApprovalStep([
        approval({ id: 1, step: 1, decision: 'approved' }),
        approval({ id: 2, step: 2, decision: 'rejected' }),
      ]),
    ).toBeNull()
  })
})
