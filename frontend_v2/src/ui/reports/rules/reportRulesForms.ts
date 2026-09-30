import type { ReportKind } from '../../../lib/reportsApi'

export type ReportRulesFormSpec = {
  /** Report name in the drawer title and on the settings page. */
  title: string
  /** Bank receipts excluded by phrases in their payment purpose: PnL only — for Cashflow they are money that arrived. */
  bankExclusions: boolean
  /** How the report dates expenses, shown under the source. */
  expenseDates: string
}

/** What differs between the rules forms of the reports; a new report adds an entry here. */
export const REPORT_RULES_FORMS: Record<ReportKind, ReportRulesFormSpec> = {
  pnl: {
    title: 'Прибыли и убытки (PnL)',
    bankExclusions: true,
    expenseDates: 'Расходы — по месяцу начисления заявки; заявки с амортизацией делятся по месяцам графика.',
  },
  cashflow: {
    title: 'Движение денег (Cashflow)',
    bankExclusions: false,
    expenseDates: 'Расходы — по дате фактической оплаты, без амортизации; выплаты по инвестициям — по дате выплаты.',
  },
}
