import { Card, Result, Skeleton, Typography } from 'antd'
import type { ReportKind } from '../../lib/reportsApi'
import { useTenantAdmin } from '../../lib/useTenantAdmin'
import { ReportRulesForm } from '../reports/rules/ReportRulesForm'
import { REPORT_RULES_FORMS } from '../reports/rules/reportRulesForms'

/** `/settings/pnl-report-config`, `/settings/cashflow-report-config`: the same rules form as the drawer on «Отчёты». */
export function ReportRulesSettingsPage({ report }: { report: ReportKind }) {
  const { isAdmin, loading } = useTenantAdmin()
  if (loading) return <Skeleton active />
  if (!isAdmin) return <Result status="403" title="Нет доступа" subTitle="Правила отчёта меняет администратор компании." />
  return (
    <div style={{ maxWidth: 960 }}>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        {`Правила отчёта: ${REPORT_RULES_FORMS[report].title}`}
      </Typography.Title>
      <Card>
        <ReportRulesForm key={report} report={report} />
      </Card>
    </div>
  )
}
