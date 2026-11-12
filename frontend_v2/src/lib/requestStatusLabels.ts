/**
 * Human names of request statuses for the mobile screens. The desktop keeps the raw codes (DRAFT, 1…5, PAYED…):
 * these helpers are used only by the phone layout.
 */

/** `feed`: a card of the requests feed; `card`: the hero of the request card (knows how many steps there are). */
export type RequestStatusLabelContext = 'feed' | 'card'

export type RequestStatusLabelOptions = {
  /** Number of approval steps of the request: the card shows «Шаг N из M» when it is known. */
  totalSteps?: number | null
  context?: RequestStatusLabelContext
}

const FIXED_LABELS: Record<string, string> = {
  DRAFT: 'Черновик',
  APPROVED: 'Согласована',
  PAYED: 'Оплачена',
  REJECTED: 'Отклонена',
}

function normalizeStatus(status: string | null | undefined): string {
  return String(status ?? '').trim().toUpperCase()
}

/** Approval step of a status «1»…«5», or null for any other status. */
export function requestStatusStep(status: string | null | undefined): number | null {
  const normalized = normalizeStatus(status)
  if (!/^[1-5]$/.test(normalized)) return null
  return Number(normalized)
}

/**
 * DRAFT → «Черновик», 1…5 → «На согласовании · шаг N» in the feed and «Шаг N из M» in the card, APPROVED →
 * «Согласована», PAYED → «Оплачена», REJECTED → «Отклонена». An unknown status is shown as it came.
 */
export function requestStatusLabel(status: string | null | undefined, options: RequestStatusLabelOptions = {}): string {
  const normalized = normalizeStatus(status)
  const fixed = FIXED_LABELS[normalized]
  if (fixed) return fixed
  const step = requestStatusStep(normalized)
  if (step !== null) {
    const total = options.totalSteps
    if (options.context === 'card' && typeof total === 'number' && Number.isFinite(total) && total >= step) {
      return `Шаг ${step} из ${total}`
    }
    return `На согласовании · шаг ${step}`
  }
  const raw = String(status ?? '').trim()
  return raw || '—'
}

/** Tone of a status tag on the mobile screens: the tag takes its text, fill and border from the matching antd tokens. */
export type RequestStatusTone = 'success' | 'processing' | 'error' | 'default'

/** Tone of a status tag on the mobile screens (names only, no literal colours). */
export function requestStatusColor(status: string | null | undefined): RequestStatusTone {
  const normalized = normalizeStatus(status)
  if (normalized === 'REJECTED') return 'error'
  if (normalized === 'APPROVED') return 'success'
  if (normalized === 'PAYED') return 'default'
  if (normalized === 'DRAFT') return 'default'
  if (requestStatusStep(normalized) !== null) return 'processing'
  return 'default'
}

/** Status chips of the mobile filter sheet (one at a time: the API filters by a single status). */
export const MOBILE_STATUS_OPTIONS: ReadonlyArray<{ value: string; label: string }> = [
  { value: 'DRAFT', label: 'Черновик' },
  { value: '1', label: 'Шаг 1' },
  { value: '2', label: 'Шаг 2' },
  { value: '3', label: 'Шаг 3' },
  { value: '4', label: 'Шаг 4' },
  { value: '5', label: 'Шаг 5' },
  { value: 'APPROVED', label: 'Согласована' },
  { value: 'PAYED', label: 'Оплачена' },
  { value: 'REJECTED', label: 'Отклонена' },
]

/** Label of a status chip of the filter sheet (or the status itself when it is not in the list). */
export function mobileStatusOptionLabel(status: string): string {
  return MOBILE_STATUS_OPTIONS.find((option) => option.value === status)?.label ?? status
}
