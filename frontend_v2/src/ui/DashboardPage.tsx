import { useEffect, useMemo, useState } from 'react'
import { Alert, Button, Card, Col, Divider, Input, Modal, Row, Skeleton, Space, Switch, Tag, Typography, message } from 'antd'
import {
  confirmPaymentViaWebApp,
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
import type { DashboardWidgetKey, PendingApprovalItem, WidgetVisibility } from './dashboard/widgets/types'
import { useUserPreference } from '../lib/useUserPreference'

const DASHBOARD_WIDGETS_PREF_KEY = 'dashboard.widgets.v1'
const defaultVisibility: WidgetVisibility = {
  pendingApprovals: true,
  incomeBreakdown: true,
  expenseBreakdown: true,
  pnlNetPrevMonth: true,
  cashflowNetCurrentMonth: true,
}

function normalizeWidgetVisibility(raw: unknown): WidgetVisibility {
  if (!raw || typeof raw !== 'object') return defaultVisibility
  return {
    ...defaultVisibility,
    ...(raw as Partial<WidgetVisibility>),
  }
}

export function DashboardPage() {
  const [approvalsLoading, setApprovalsLoading] = useState(true)
  const [reportsLoading, setReportsLoading] = useState(true)
  const [approvalsBusy, setApprovalsBusy] = useState(false)
  const [pendingApprovals, setPendingApprovals] = useState<ReturnType<typeof toPendingApprovals>>([])
  const [pnlPayload, setPnlPayload] = useState<LegacyReportPayload | null>(null)
  const [cashflowPayload, setCashflowPayload] = useState<LegacyReportPayload | null>(null)
  const [reportsError, setReportsError] = useState<string | null>(null)
  const [approvalsError, setApprovalsError] = useState<string | null>(null)
  const [paymentModalOpen, setPaymentModalOpen] = useState(false)
  const [paymentModalItem, setPaymentModalItem] = useState<PendingApprovalItem | null>(null)
  const [paymentExpenseId, setPaymentExpenseId] = useState('')

  const { value: widgetVisibility, setValue: setWidgetVisibility } = useUserPreference<WidgetVisibility>({
    key: DASHBOARD_WIDGETS_PREF_KEY,
    defaultValue: defaultVisibility,
    normalize: (raw) => normalizeWidgetVisibility(raw),
    debounceMs: 250,
  })

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

  const openPayoutModal = (item: PendingApprovalItem) => {
    setPaymentModalItem(item)
    setPaymentExpenseId('')
    setPaymentModalOpen(true)
  }

  const closePayoutModal = () => {
    setPaymentModalOpen(false)
    setPaymentModalItem(null)
    setPaymentExpenseId('')
  }

  const confirmPayout = async () => {
    const item = paymentModalItem
    if (!item) return
    const expenseId = paymentExpenseId.trim()
    if (!expenseId) {
      message.warning('Введите номер платежа')
      return
    }
    setApprovalsBusy(true)
    try {
      await confirmPaymentViaWebApp({ approval_id: item.approvalId, expense_id: expenseId })
      message.success('Выплата подтверждена')
      closePayoutModal()
      await loadApprovals()
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : 'Не удалось подтвердить выплату')
    } finally {
      setApprovalsBusy(false)
    }
  }

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Card>
        <Typography.Title level={4} style={{ marginTop: 0 }}>
          Рабочая панель
        </Typography.Title>
        <Typography.Text type="secondary">Ключевые показатели и задачи на сегодня.</Typography.Text>
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
              onPayout={openPayoutModal}
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

      <Modal
        open={paymentModalOpen}
        title="Выплатить"
        onCancel={closePayoutModal}
        footer={null}
        destroyOnClose
      >
        <Space direction="vertical" size={12} style={{ display: 'flex' }}>
          <Typography.Text type="secondary">Введите `expense_id` для подтверждения выплаты.</Typography.Text>
          <Input
            value={paymentExpenseId}
            onChange={(e) => setPaymentExpenseId(e.target.value)}
            placeholder="Номер платежа"
            onPressEnter={() => void confirmPayout()}
          />
          <Button type="primary" block loading={approvalsBusy} onClick={() => void confirmPayout()}>
            Выплатить
          </Button>
        </Space>
      </Modal>

    </Space>
  )
}

