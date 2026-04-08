import { useEffect, useMemo, useState } from 'react'
import { Alert, Button, Card, Col, Divider, Row, Skeleton, Space, Switch, Tag, Typography, message } from 'antd'
import {
  apiFetch,
  getCashflowReportData,
  getMyApprovals,
  getPnlReportData,
  setRequestApprovalDecision,
  type LegacyReportPayload,
} from '../lib/api'
import { ExpensePieWidget } from './dashboard/widgets/ExpensePieWidget'
import { IncomePieWidget } from './dashboard/widgets/IncomePieWidget'
import { PendingApprovalsWidget } from './dashboard/widgets/PendingApprovalsWidget'
import { PnlNetProfitPrevMonthWidget } from './dashboard/widgets/PnlNetProfitPrevMonthWidget'
import { CashflowProfitCurrentMonthWidget } from './dashboard/widgets/CashflowProfitCurrentMonthWidget'
import { buildCategorySlices, getCurrentMonthRef, getPreviousMonthRef, toPendingApprovals, totalsFromReport } from './dashboard/widgets/adapters'
import type { DashboardWidgetKey, WidgetVisibility } from './dashboard/widgets/types'

type ModuleRow = {
  module_key: string
  display_name: string
  tenant_enabled: boolean
  user_allowed: boolean
  effective_enabled: boolean
}

export function DashboardPage() {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [modules, setModules] = useState<ModuleRow[]>([])
  const [approvalsLoading, setApprovalsLoading] = useState(true)
  const [reportsLoading, setReportsLoading] = useState(true)
  const [approvalsBusy, setApprovalsBusy] = useState(false)
  const [pendingApprovals, setPendingApprovals] = useState<ReturnType<typeof toPendingApprovals>>([])
  const [pnlPayload, setPnlPayload] = useState<LegacyReportPayload | null>(null)
  const [cashflowPayload, setCashflowPayload] = useState<LegacyReportPayload | null>(null)
  const [reportsError, setReportsError] = useState<string | null>(null)
  const [approvalsError, setApprovalsError] = useState<string | null>(null)

  const WIDGET_STORAGE_KEY = 'dashboard.widgets.v1'
  const defaultVisibility: WidgetVisibility = {
    pendingApprovals: true,
    incomeBreakdown: true,
    expenseBreakdown: true,
    pnlNetPrevMonth: true,
    cashflowNetCurrentMonth: true,
  }
  const [widgetVisibility, setWidgetVisibility] = useState<WidgetVisibility>(() => {
    try {
      const raw = localStorage.getItem(WIDGET_STORAGE_KEY)
      if (!raw) return defaultVisibility
      const parsed = JSON.parse(raw) as Partial<WidgetVisibility>
      return { ...defaultVisibility, ...parsed }
    } catch {
      return defaultVisibility
    }
  })

  useEffect(() => {
    localStorage.setItem(WIDGET_STORAGE_KEY, JSON.stringify(widgetVisibility))
  }, [widgetVisibility])

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setLoading(true)
      setError(null)
      try {
        const res = await apiFetch('/api/modules/')
        if (!res.ok) throw new Error(`Ошибка HTTP ${res.status}`)
        const data = (await res.json()) as { modules: ModuleRow[] }
        if (!cancelled) setModules(data.modules || [])
      } catch (e: any) {
        if (!cancelled) setError(e?.message || 'Не удалось загрузить модули')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const loadApprovals = async () => {
    setApprovalsLoading(true)
    setApprovalsError(null)
    try {
      const groups = await getMyApprovals()
      setPendingApprovals(toPendingApprovals(groups))
    } catch (e: unknown) {
      setApprovalsError(e instanceof Error ? e.message : 'Не удалось загрузить мои согласования')
    } finally {
      setApprovalsLoading(false)
    }
  }

  const loadReports = async () => {
    setReportsLoading(true)
    setReportsError(null)
    try {
      const [pnl, cashflow] = await Promise.all([getPnlReportData(), getCashflowReportData()])
      setPnlPayload(pnl)
      setCashflowPayload(cashflow)
    } catch (e: unknown) {
      setReportsError(e instanceof Error ? e.message : 'Не удалось загрузить отчеты')
    } finally {
      setReportsLoading(false)
    }
  }

  useEffect(() => {
    void loadApprovals()
    void loadReports()
  }, [])

  const nowRef = getCurrentMonthRef()
  const prevRef = getPreviousMonthRef(nowRef)

  const pnlTotals = useMemo(
    () => totalsFromReport(pnlPayload?.revenue ?? [], pnlPayload?.expense ?? []),
    [pnlPayload?.revenue, pnlPayload?.expense],
  )
  const cashflowTotals = useMemo(
    () => totalsFromReport(cashflowPayload?.revenue ?? [], cashflowPayload?.expense ?? []),
    [cashflowPayload?.revenue, cashflowPayload?.expense],
  )

  const pnlPrevMonthProfit = (pnlTotals.incomeByMonth[prevRef.monthIndex] ?? 0) + (pnlTotals.expenseByMonth[prevRef.monthIndex] ?? 0)
  const cashflowCurrentProfit =
    (cashflowTotals.incomeByMonth[nowRef.monthIndex] ?? 0) + (cashflowTotals.expenseByMonth[nowRef.monthIndex] ?? 0)

  const incomeSlices = useMemo(() => buildCategorySlices(pnlPayload?.revenue ?? []), [pnlPayload?.revenue])
  const expenseSlices = useMemo(() => buildCategorySlices(pnlPayload?.expense ?? []), [pnlPayload?.expense])

  const handleDecision = async (requestId: number, step: number, decision: 'approved' | 'rejected') => {
    setApprovalsBusy(true)
    try {
      await setRequestApprovalDecision({ requestId, step, decision })
      message.success(decision === 'approved' ? 'Шаг согласования одобрен' : 'Шаг согласования отклонен')
      await loadApprovals()
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : 'Не удалось обновить согласование')
    } finally {
      setApprovalsBusy(false)
    }
  }

  const toggleWidget = (key: DashboardWidgetKey, value: boolean) => {
    setWidgetVisibility((prev) => ({ ...prev, [key]: value }))
  }

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Card>
        <Typography.Title level={4} style={{ marginTop: 0 }}>
          Панель модулей
        </Typography.Title>
        <Typography.Text type="secondary">
          Текущий хост: <span className="mono">{location.host}</span>
        </Typography.Text>
        <Divider style={{ margin: '12px 0' }} />
        <Space wrap>
          <Typography.Text strong>Виджеты:</Typography.Text>
          <Switch
            checked={widgetVisibility.pendingApprovals}
            onChange={(checked) => toggleWidget('pendingApprovals', checked)}
            checkedChildren="Согласования"
            unCheckedChildren="Согласования"
          />
          <Switch
            checked={widgetVisibility.incomeBreakdown}
            onChange={(checked) => toggleWidget('incomeBreakdown', checked)}
            checkedChildren="Доходы"
            unCheckedChildren="Доходы"
          />
          <Switch
            checked={widgetVisibility.expenseBreakdown}
            onChange={(checked) => toggleWidget('expenseBreakdown', checked)}
            checkedChildren="Расходы"
            unCheckedChildren="Расходы"
          />
          <Switch
            checked={widgetVisibility.pnlNetPrevMonth}
            onChange={(checked) => toggleWidget('pnlNetPrevMonth', checked)}
            checkedChildren="P&L"
            unCheckedChildren="P&L"
          />
          <Switch
            checked={widgetVisibility.cashflowNetCurrentMonth}
            onChange={(checked) => toggleWidget('cashflowNetCurrentMonth', checked)}
            checkedChildren="Cashflow"
            unCheckedChildren="Cashflow"
          />
          <Button onClick={() => setWidgetVisibility(defaultVisibility)}>Сбросить настройки виджетов</Button>
        </Space>
      </Card>

      {approvalsError ? <Alert type="error" showIcon message="Ошибка загрузки согласований" description={approvalsError} /> : null}
      {reportsError ? <Alert type="error" showIcon message="Ошибка загрузки отчетов" description={reportsError} /> : null}

      <Row gutter={[16, 16]}>
        {widgetVisibility.pendingApprovals ? (
          <Col xs={24} lg={12}>
            <PendingApprovalsWidget
              items={pendingApprovals}
              loading={approvalsLoading}
              busy={approvalsBusy}
              onApprove={(item) => handleDecision(item.requestId, item.step, 'approved')}
              onReject={(item) => handleDecision(item.requestId, item.step, 'rejected')}
            />
          </Col>
        ) : null}
        {widgetVisibility.pnlNetPrevMonth ? (
          <Col xs={24} sm={12} lg={6}>
            <PnlNetProfitPrevMonthWidget value={pnlPrevMonthProfit} loading={reportsLoading} />
          </Col>
        ) : null}
        {widgetVisibility.cashflowNetCurrentMonth ? (
          <Col xs={24} sm={12} lg={6}>
            <CashflowProfitCurrentMonthWidget value={cashflowCurrentProfit} loading={reportsLoading} />
          </Col>
        ) : null}
      </Row>

      <Row gutter={[16, 16]}>
        {widgetVisibility.incomeBreakdown ? (
          <Col xs={24} lg={12}>
            <IncomePieWidget slices={incomeSlices} loading={reportsLoading} />
          </Col>
        ) : null}
        {widgetVisibility.expenseBreakdown ? (
          <Col xs={24} lg={12}>
            <ExpensePieWidget slices={expenseSlices} loading={reportsLoading} />
          </Col>
        ) : null}
      </Row>

      {loading ? <Skeleton active /> : null}
      {error ? <Alert type="error" showIcon message="Не удалось загрузить модули" description={error} /> : null}

      <Row gutter={[16, 16]}>
        {(modules || []).map((m) => (
          <Col key={m.module_key} xs={24} md={12}>
            <Card
              title={m.display_name}
              extra={<Tag color={m.effective_enabled ? 'green' : 'default'}>{m.effective_enabled ? 'Доступен' : 'Отключен'}</Tag>}
            >
              <Space direction="vertical" size={4}>
                <Typography.Text type="secondary">
                  Ключ: <span className="mono">{m.module_key}</span>
                </Typography.Text>
                <Typography.Text type="secondary">
                  Включен у тенанта: <span className="mono">{String(m.tenant_enabled)}</span>
                </Typography.Text>
                <Typography.Text type="secondary">
                  Разрешен пользователю: <span className="mono">{String(m.user_allowed)}</span>
                </Typography.Text>
              </Space>
            </Card>
          </Col>
        ))}
      </Row>

      {!loading && !modules.length ? <Alert type="info" showIcon message="Список модулей пуст." /> : null}
    </Space>
  )
}

