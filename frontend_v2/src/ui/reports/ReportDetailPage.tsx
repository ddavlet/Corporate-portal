import { SettingOutlined } from '@ant-design/icons'
import { Button, Result, Skeleton, Tag, Typography } from 'antd'
import { lazy, Suspense, useEffect, useMemo, useState, type ComponentType, type LazyExoticComponent } from 'react'
import { useLocation, useParams } from 'react-router-dom'
import { isReportKind, type ReportKey } from '../../lib/reportsApi'
import { useReportTemplates } from '../../lib/useReportTemplates'
import { useTenantAdmin } from '../../lib/useTenantAdmin'
import { AllReportsLink, ReportNotFoundPage } from './ReportNotFoundPage'
import { buildReportCards, resolveReportCard } from './reportCards'
import { rememberView } from './reportViewMemory'
import { ReportRulesDrawer } from './rules/ReportRulesDrawer'
import { REPORT_TEMPLATE_REGISTRY } from './templates/registry'
import type { ReportTemplateProps } from './templates/types'

type CardComponent = LazyExoticComponent<ComponentType<ReportTemplateProps<ReportKey>>>

/** One lazy component per template (and per report with its own page), created once, so moving between cards of one
 * template does not reload its code. */
const lazyTemplates = new Map<string, CardComponent>()

function cardComponent(template: string, report: ReportKey): CardComponent {
  const own = REPORT_TEMPLATE_REGISTRY[template].reports[report]?.load
  const key = own ? `${template}/${report}` : template
  let component = lazyTemplates.get(key)
  if (!component) {
    // Without a page of its own a card is a statement report (ReportKind), which is what the template shows.
    component = lazy(own ?? (REPORT_TEMPLATE_REGISTRY[template].load as NonNullable<typeof own>))
    lazyTemplates.set(key, component)
  }
  return component
}

/** `/reports/:template/:report`: one report in one template; only that template's code and that report's data load. */
export function ReportDetailPage() {
  const { template = '', report = '' } = useParams()
  const { search } = useLocation()
  const { templates, failed, loading, retry } = useReportTemplates()
  const { isAdmin } = useTenantAdmin()
  const [rulesOpen, setRulesOpen] = useState(false)
  const [rulesVersion, setRulesVersion] = useState(0)
  const known = failed ? null : templates
  const resolution = useMemo(
    () => (loading ? null : resolveReportCard(known, template, report)),
    [loading, known, template, report],
  )
  const card = resolution?.status === 'ok' ? resolution.card : null

  useEffect(() => {
    if (card) rememberView(card.template, card.report, search, REPORT_TEMPLATE_REGISTRY[card.template].transientParams)
  }, [card, search])

  if (!resolution) return <Skeleton active />
  if (resolution.status === 'unknown') return <ReportNotFoundPage />
  if (resolution.status === 'not-allowed' && failed) {
    // Without the template list only Classic is known; the company may well allow this template.
    return (
      <Result
        status="warning"
        title={`Шаблон «${resolution.templateLabel}» сейчас недоступен`}
        subTitle="Не удалось загрузить список шаблонов. Попробуйте ещё раз."
        extra={[
          <Button key="retry" type="primary" onClick={retry}>
            Повторить
          </Button>,
          <AllReportsLink key="back" />,
        ]}
      />
    )
  }
  if (resolution.status === 'not-allowed') {
    return (
      <Result
        status="403"
        title={`Шаблон «${resolution.templateLabel}» недоступен`}
        subTitle="Администратор компании не включил этот шаблон."
        extra={<AllReportsLink />}
      />
    )
  }

  const current = resolution.card
  const Template = cardComponent(current.template, current.report)
  const rulesReport = isReportKind(current.report) ? current.report : null
  const openRules = isAdmin && rulesReport ? () => setRulesOpen(true) : null
  return (
    <>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', marginBottom: 12 }}>
        <AllReportsLink />
        <Typography.Title level={4} style={{ margin: 0 }}>
          {current.title}
        </Typography.Title>
        <Tag>{current.templateLabel}</Tag>
        {openRules ? (
          <Button type="text" icon={<SettingOutlined />} aria-label={`Правила отчёта «${current.title}»`} onClick={openRules} />
        ) : null}
      </div>
      <Suspense fallback={<Skeleton active />}>
        <Template report={current.report} onOpenRules={openRules} rulesVersion={rulesVersion} />
      </Suspense>
      <ReportRulesDrawer
        report={rulesOpen ? rulesReport : null}
        cards={buildReportCards(known)}
        onClose={() => setRulesOpen(false)}
        onSaved={() => setRulesVersion((version) => version + 1)}
      />
    </>
  )
}
