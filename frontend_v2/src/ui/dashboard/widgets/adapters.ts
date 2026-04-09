import type { LegacyReportItem, MyApprovalGroup } from '../../../lib/api'
import type { CategorySlice, PendingApprovalItem, ReportMonthRef, ReportTotals } from './types'

const REPORT_TZ = 'Asia/Tashkent'

function parseAmount(value: unknown): number {
  if (typeof value === 'number') return Number.isFinite(value) ? value : 0
  if (typeof value !== 'string') return 0
  const normalized = value.replace(/\s+/g, '').replace(',', '.')
  const parsed = Number(normalized)
  return Number.isFinite(parsed) ? parsed : 0
}

function parseReportDate(input: unknown): Date | null {
  if (typeof input !== 'string' || !input.trim()) return null
  const parsed = new Date(input)
  return Number.isNaN(parsed.getTime()) ? null : parsed
}

function getMonthRef(date: Date): ReportMonthRef {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: REPORT_TZ,
    year: 'numeric',
    month: '2-digit',
  }).formatToParts(date)
  const yearPart = parts.find((p) => p.type === 'year')?.value ?? ''
  const monthPart = parts.find((p) => p.type === 'month')?.value ?? ''
  const year = Number(yearPart)
  const monthIndex = Number(monthPart) - 1
  return { year, monthIndex }
}

function categoryFromItem(item: LegacyReportItem): string {
  return (
    item.category ||
    item.cathegory ||
    item.cat ||
    item.cat_name ||
    item.article ||
    item.item ||
    'Без категории'
  )
}

export function toPendingApprovals(groups: MyApprovalGroup[]): PendingApprovalItem[] {
  const result: PendingApprovalItem[] = []
  for (const group of groups) {
    const requestStatus = String(group.request.status || '').trim().toUpperCase()
    const pendingSteps = (group.approvals || []).filter((x) => {
      if (String(x.decision || '').toLowerCase() !== 'pending') return false
      const isPayment = String(x.step_type || '').toLowerCase() === 'payment'
      // Active step rule for dashboard actions:
      // - serial steps: request status equals step number ("1".."5")
      // - payment step: request is already APPROVED and waits for payout confirmation
      return requestStatus === String(x.step) || (isPayment && requestStatus === 'APPROVED')
    })
    if (!pendingSteps.length) continue
    const step = pendingSteps[0]
    if (!step) continue
    const amount = parseAmount(group.request.amount)
    result.push({
      approvalId: step.id,
      requestId: group.request.id,
      title: group.request.title || `Заявка #${group.request.id}`,
      amountText: new Intl.NumberFormat('ru-RU').format(amount || 0),
      currency: group.request.currency || null,
      step: step.step,
      stepType: String(step.step_type || '').toLowerCase(),
      paymentActionMode: step.payment_action_mode ?? null,
    })
  }
  return result
}

export function buildMonthlyTotals(items: LegacyReportItem[]): ReportTotals {
  const incomeByMonth = Array(12).fill(0) as number[]
  const expenseByMonth = Array(12).fill(0) as number[]
  for (const item of items) {
    const date = parseReportDate(item.date)
    if (!date) continue
    const monthRef = getMonthRef(date)
    if (monthRef.monthIndex < 0 || monthRef.monthIndex > 11) continue
    const amount = parseAmount(item.amount)
    if (amount >= 0) incomeByMonth[monthRef.monthIndex] += amount
    else expenseByMonth[monthRef.monthIndex] += amount
  }
  return { incomeByMonth, expenseByMonth }
}

export function totalsFromReport(revenueItems: LegacyReportItem[], expenseItems: LegacyReportItem[]): ReportTotals {
  const incomeByMonth = Array(12).fill(0) as number[]
  const expenseByMonth = Array(12).fill(0) as number[]
  for (const row of revenueItems) {
    const date = parseReportDate(row.date)
    if (!date) continue
    const { monthIndex } = getMonthRef(date)
    incomeByMonth[monthIndex] += parseAmount(row.amount)
  }
  for (const row of expenseItems) {
    const date = parseReportDate(row.date)
    if (!date) continue
    const { monthIndex } = getMonthRef(date)
    expenseByMonth[monthIndex] += parseAmount(row.amount)
  }
  return { incomeByMonth, expenseByMonth }
}

export function buildCategorySlices(items: LegacyReportItem[]): CategorySlice[] {
  const map = new Map<string, number>()
  for (const item of items) {
    const label = categoryFromItem(item)
    const amount = Math.abs(parseAmount(item.amount))
    map.set(label, (map.get(label) ?? 0) + amount)
  }
  return Array.from(map.entries())
    .map(([label, amount]) => ({ label, amount }))
    .sort((a, b) => b.amount - a.amount)
}

export function getCurrentMonthRef(): ReportMonthRef {
  const now = new Date()
  return getMonthRef(now)
}

export function getPreviousMonthRef(current: ReportMonthRef): ReportMonthRef {
  if (current.monthIndex > 0) return { year: current.year, monthIndex: current.monthIndex - 1 }
  return { year: current.year - 1, monthIndex: 11 }
}
