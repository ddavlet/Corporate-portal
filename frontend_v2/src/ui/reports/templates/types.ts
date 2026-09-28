import type { ComponentType, ReactNode } from 'react'
import type { ReportKind } from '../../../lib/reportsApi'

export type ReportTemplateProps = {
  /** Template switcher from the page shell; null when only one template is allowed. The template places it in its header. */
  templateSwitcher: ReactNode | null
}

export type ReportTemplateDefinition = {
  key: string
  label: string
  supports: ReportKind[]
  /** Loaded with React.lazy by the page shell, so a template's code is fetched only when it is shown. */
  load: () => Promise<{ default: ComponentType<ReportTemplateProps> }>
}
