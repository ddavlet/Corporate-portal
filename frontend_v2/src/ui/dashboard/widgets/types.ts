import type { MyApprovalGroup } from '../../../lib/api'

export type DashboardWidgetKey =
  | 'pendingApprovals'
  | 'activeRequests'
  | 'incomeBreakdown'
  | 'expenseBreakdown'
  | 'pnlNetPrevMonth'
  | 'cashflowNetCurrentMonth'

export type WidgetVisibility = Record<DashboardWidgetKey, boolean>

export type PendingApprovalItem = {
  approvalId: number
  requestId: number
  title: string
  description: string | null
  amountText: string
  currency: string | null
  step: number
  stepType: string
  paymentActionMode?: string | null
}

export type CategorySlice = {
  label: string
  amount: number
}

export type ReportTotals = {
  incomeByMonth: number[]
  expenseByMonth: number[]
}

export type DashboardData = {
  pendingApprovals: PendingApprovalItem[]
  pnlTotals: ReportTotals
  cashflowTotals: ReportTotals
  incomeSlices: CategorySlice[]
  expenseSlices: CategorySlice[]
}

export type ReportMonthRef = {
  year: number
  monthIndex: number
}

export type ApprovalGroups = MyApprovalGroup[]
