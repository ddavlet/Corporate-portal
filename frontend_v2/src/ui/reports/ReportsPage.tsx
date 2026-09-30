import { Col, Row, Skeleton, Typography } from 'antd'
import { useState } from 'react'
import { Navigate, useSearchParams } from 'react-router-dom'
import type { ReportKind } from '../../lib/reportsApi'
import { useReportTemplates } from '../../lib/useReportTemplates'
import { useTenantAdmin } from '../../lib/useTenantAdmin'
import { ReportCardWidget } from './ReportCardWidget'
import { buildReportCards, legacyReportPath } from './reportCards'
import { rememberedView } from './reportViewMemory'
import { ReportRulesDrawer } from './rules/ReportRulesDrawer'

/** «Отчёты»: one card per report; a report's data is loaded only on its own page. */
export function ReportsPage() {
  const [params] = useSearchParams()
  const { templates, failed, loading } = useReportTemplates()
  const { isAdmin } = useTenantAdmin()
  const [rulesFor, setRulesFor] = useState<ReportKind | null>(null)

  if (loading) return <Skeleton active />
  const known = failed ? null : templates
  const legacy = legacyReportPath(params, known)
  if (legacy) return <Navigate to={legacy} replace />
  const cards = buildReportCards(known)

  return (
    <>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        Отчёты
      </Typography.Title>
      <Row gutter={[16, 16]}>
        {cards.map((card) => (
          <Col key={card.path} xs={24} md={12}>
            <ReportCardWidget
              card={card}
              href={`${card.path}${rememberedView(card.template, card.report)}`}
              onOpenRules={isAdmin ? () => setRulesFor(card.report) : null}
            />
          </Col>
        ))}
      </Row>
      <ReportRulesDrawer report={rulesFor} cards={cards} onClose={() => setRulesFor(null)} />
    </>
  )
}
