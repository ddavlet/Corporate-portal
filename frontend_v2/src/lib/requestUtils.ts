const dateFmtTashkent = new Intl.DateTimeFormat('ru-RU', {
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  timeZone: 'Asia/Tashkent',
})
const billingMonthFmtTashkent = new Intl.DateTimeFormat('ru-RU', {
  month: 'long',
  year: 'numeric',
  timeZone: 'Asia/Tashkent',
})

export function formatRequestDate(value?: string | null): string {
  if (!value) return '-'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return '-'
  return dateFmtTashkent.format(parsed)
}

export function formatRequestBillingMonth(value?: string | null): string {
  if (!value) return '-'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return '-'
  return billingMonthFmtTashkent.format(parsed)
}

export function getRequestStatusColor(value: string): string | undefined {
  const normalized = String(value || '').trim().toUpperCase()
  if (normalized === 'REJECTED') return 'error'
  if (normalized === 'APPROVED') return 'success'
  if (normalized === 'PAYED') return '#8c8c8c'
  const numericStatus = Number(normalized)
  if (Number.isFinite(numericStatus) && numericStatus >= 1 && numericStatus <= 5) return 'warning'
  return undefined
}

export function canResendRequestByStatus(status?: string | null): boolean {
  const raw = String(status || '').trim()
  if (raw.toUpperCase() === 'APPROVED') return true
  const numeric = Number(raw)
  return Number.isFinite(numeric) && numeric >= 1 && numeric <= 5
}
