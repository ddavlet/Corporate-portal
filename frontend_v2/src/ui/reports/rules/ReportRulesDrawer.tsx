import { Alert, Drawer, Grid } from 'antd'
import { useState } from 'react'
import type { ReportKind } from '../../../lib/reportsApi'
import type { ReportCard } from '../reportCards'
import { ReportRulesForm } from './ReportRulesForm'
import { REPORT_RULES_FORMS } from './reportRulesForms'

type Props = {
  /** The report whose rules are open; null closes the drawer. */
  report: ReportKind | null
  /** Cards on the page: the drawer names those that share these rules. */
  cards: ReportCard[]
  onClose: () => void
  /** After a successful save, e.g. to reload the open report. */
  onSaved?: () => void
}

/** «A», «A» и «B», «A», «B» и «C». */
function listRu(items: string[]): string {
  return items.length < 2 ? (items[0] ?? '') : `${items.slice(0, -1).join(', ')} и ${items[items.length - 1]}`
}

function sharedCardsNote(report: ReportKind, cards: ReportCard[]): string | null {
  const titles = cards.filter((card) => card.report === report).map((card) => `«${card.title}»`)
  if (titles.length === 0) return null
  return titles.length === 1
    ? `Эти правила использует карточка ${titles[0]}.`
    : `Эти правила используют карточки ${listRu(titles)}.`
}

/** A report's rules next to the cards or the open report. */
export function ReportRulesDrawer({ report, cards, onClose, onSaved }: Props) {
  const isPhone = !Grid.useBreakpoint().md
  // Keeps the last report while the drawer slides out; destroyOnHidden then unmounts the form.
  const [shown, setShown] = useState<ReportKind | null>(report)
  if (report !== null && report !== shown) setShown(report)
  const note = shown ? sharedCardsNote(shown, cards) : null
  return (
    <Drawer
      open={report !== null}
      onClose={onClose}
      width={isPhone ? '100%' : 720}
      destroyOnHidden
      title={shown ? `Правила отчёта: ${REPORT_RULES_FORMS[shown].title}` : null}
    >
      {shown ? (
        <>
          {note ? <Alert type="info" showIcon message={note} style={{ marginBottom: 16 }} /> : null}
          <ReportRulesForm key={shown} report={shown} onSaved={onSaved} />
        </>
      ) : null}
    </Drawer>
  )
}
