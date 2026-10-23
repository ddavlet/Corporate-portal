import { formatExact } from '../../../../lib/reportsFormat'

/** Exact amount; with `dashForZero` a day without income or expense shows «—» instead of «0». */
export function balanceAmount(value: string, dashForZero = false): string {
  if (dashForZero && Number(value) === 0) return '—'
  return formatExact(value)
}

/** «1 операция», «3 операции», «5 операций». */
export function countLabel(count: number): string {
  const tens = count % 100
  const ones = count % 10
  const word =
    tens >= 11 && tens <= 14 ? 'операций' : ones === 1 ? 'операция' : ones >= 2 && ones <= 4 ? 'операции' : 'операций'
  return `${count} ${word}`
}
