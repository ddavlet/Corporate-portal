import type { ComponentType } from 'react'
import type { ReportKind } from '../../../lib/reportsApi'

export type ReportTemplateProps = {
  /** The report of the card; the template loads and shows only this one. */
  report: ReportKind
  /** Opens the rules drawer of this report; null when the user may not change the rules. */
  onOpenRules: (() => void) | null
  /** Grows after the rules are saved: the template loads its report again. */
  rulesVersion: number
}

/** One card on «Отчёты»: a report as this template shows it. */
export type ReportCardInfo = { title: string; description: string }

export type ReportTemplateDefinition = {
  key: string
  label: string
  /** One card per report; the keys are the reports this template shows, in card order. */
  reports: Partial<Record<ReportKind, ReportCardInfo>>
  /** URL parameters a card does not remember when the user leaves it (an open drill-down, for example). */
  transientParams?: readonly string[]
  /** Parameters this template put in the address of «Отчёты» before the cards: an old link with any of them and no `t` was made here. */
  legacyParams?: readonly string[]
  /** Loaded with React.lazy by the page shell, so a template's code is fetched only when it is shown. */
  load: () => Promise<{ default: ComponentType<ReportTemplateProps> }>
}
