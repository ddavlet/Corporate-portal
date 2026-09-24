import { Alert, Button } from 'antd'
import type { StatementWarning } from '../../../../lib/reportsApi'
import { formatAmount, UNITS_LABEL, type Units } from '../../../../lib/reportsFormat'

type Props = { warnings: StatementWarning[]; units: Units; isAdmin: boolean; onOpenSettings: () => void }

/** Paid requests that fell out of the report because their payment purpose has no section (admins only). */
export function DataWarningBanner({ warnings, units, isAdmin, onOpenSettings }: Props) {
  const warning = warnings.find((item) => item.code === 'unassigned_purposes')
  if (!isAdmin || !warning) return null
  const purposes = warning.purposes.map((purpose) => `«${purpose}»`).join(', ')
  return (
    <Alert
      type="warning"
      showIcon
      message={`Не попали в отчёт оплаченные заявки: ${warning.count} шт. на ${formatAmount(warning.amount, units)} ${UNITS_LABEL[units]}. У назначений платежа не выбран раздел: ${purposes}.`}
      action={
        <Button size="small" onClick={onOpenSettings}>
          Распределить
        </Button>
      }
    />
  )
}
