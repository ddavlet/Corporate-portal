import type { PayrollDocumentStatus } from '../../lib/api'

/** Цвета Tag для статусов документа начисления — общие для списка и карточки. */
export const PAYROLL_STATUS_COLORS: Record<PayrollDocumentStatus, string> = {
  draft: 'default',
  accepted: 'blue',
  closed: 'green',
  cancelled: 'red',
}
