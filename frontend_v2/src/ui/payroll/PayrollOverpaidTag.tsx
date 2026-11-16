import { Tag, Tooltip } from 'antd'
import { fmtMoney } from './payrollFormat'

/** Text of the breakdown under the «Переплата» tag: what was accrued and where the money came from. */
export function overpaidBreakdown(accrued: string | number, cash: string | number, card: string | number): string {
  return `Начислено ${fmtMoney(accrued)} · касса ${fmtMoney(cash)} · карта ${fmtMoney(card)}`
}

/** Red «Переплата N» tag (cash + card above the accrued sum); nothing when there is no overpayment. */
export function PayrollOverpaidTag({
  overpaid,
  accrued,
  cash,
  card,
}: {
  overpaid: string | number | null | undefined
  accrued: string | number
  cash: string | number
  card: string | number | null | undefined
}) {
  if (!(Number(overpaid ?? 0) > 0)) return null
  const breakdown = overpaidBreakdown(accrued, cash, card ?? 0)
  return (
    <Tooltip title={breakdown}>
      <Tag color="red" tabIndex={0} aria-label={`Переплата ${fmtMoney(overpaid as string | number)}. ${breakdown}`}>
        Переплата {fmtMoney(overpaid as string | number)}
      </Tag>
    </Tooltip>
  )
}
