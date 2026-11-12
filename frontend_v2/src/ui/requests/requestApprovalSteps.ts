import type { ApprovalItem } from './RequestDetailModal'

export function isPaymentApprovalStep(a: ApprovalItem): boolean {
  return String(a.step_type || '').toLowerCase() === 'payment'
}

export function isNotificationApprovalStep(a: ApprovalItem): boolean {
  return String(a.step_type || '').toLowerCase() === 'notification'
}

/** Smallest step number that still has pending approvals (matches backend workflow). */
export function minPendingApprovalStep(approvals: ApprovalItem[] | undefined): number | null {
  if (!approvals?.length) return null
  const pendingSteps = approvals
    .filter((a) => String(a.decision || '').toLowerCase() === 'pending')
    .map((a) => a.step)
  if (!pendingSteps.length) return null
  return Math.min(...pendingSteps)
}
