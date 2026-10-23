import { DownloadOutlined, ReloadOutlined } from '@ant-design/icons'
import { Alert, Button, Card, Col, DatePicker, Empty, Result, Row, Segmented, Select, Skeleton, Space, Typography } from 'antd'
import dayjs, { type Dayjs } from 'dayjs'
import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { notifyApiError } from '../../../../lib/apiNotify'
import {
  downloadAccountBalancesXlsx,
  getAccountBalances,
  getBalanceAccounts,
  type AccountBalancesResponse,
  type BalanceAccount,
  type BalanceAccountType,
  type ReportKey,
} from '../../../../lib/reportsApi'
import { describeReportError } from '../../../../lib/reportErrors'
import { formatDate } from '../../../../lib/reportsFormat'
import { saveFile } from '../../../../lib/saveFile'
import type { ReportTemplateProps } from '../types'
import { BalanceDaysTableWidget } from './BalanceDaysTableWidget'
import { balanceAmount, countLabel } from './balancesFormat'
import { readBalancesState, toBalancesQuery, writeBalancesState, type BalancesMode, type BalancesUrlState } from './balancesUrlState'
import './balances.css'

const ISO = 'YYYY-MM-DD'
const TYPE_ORDER: BalanceAccountType[] = ['bank', 'cash', 'corporate_card']

type Loaded<T> = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ok'; data: T }

function accountLabel(account: BalanceAccount): string {
  const hidden = account.hidden ? ' (скрыта)' : ''
  return `${account.name} · ${account.currency}${hidden}`
}

function Kpi({ label, value, currency, tone }: { label: string; value: string; currency: string; tone?: 'success' | 'danger' }) {
  const sign = tone === 'success' ? '+' : tone === 'danger' ? '−' : ''
  return (
    <Card size="small" className="balances-kpi">
      <Typography.Text type="secondary">{label}</Typography.Text>
      <div className="balances-kpi-value">
        <Typography.Text type={tone} strong>
          {Number(value) === 0 || !sign ? balanceAmount(value) : `${sign}${balanceAmount(value)}`}
        </Typography.Text>{' '}
        <Typography.Text type="secondary">{currency}</Typography.Text>
      </div>
    </Card>
  )
}

/** «Остатки по счетам»: one account's balance at the start and end of a period and of every day in it, to find the
 * day the portal stopped matching the bank. */
export function AccountBalancesReport(_props: ReportTemplateProps<ReportKey>) {
  const [params, setParams] = useSearchParams()
  const state = readBalancesState(params)
  const [accounts, setAccounts] = useState<Loaded<BalanceAccount[]>>({ status: 'loading' })
  // The last report stays on screen while the next one loads.
  const [lastData, setLastData] = useState<AccountBalancesResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // Separate keys: refreshing the report must not reload the account list (that would blank the page).
  const [accountsKey, setAccountsKey] = useState(0)
  const [reloadKey, setReloadKey] = useState(0)
  const [exporting, setExporting] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    setAccounts({ status: 'loading' })
    getBalanceAccounts(controller.signal)
      .then((data) => setAccounts({ status: 'ok', data }))
      .catch((e: unknown) => {
        if (!controller.signal.aborted) setAccounts({ status: 'error', message: describeReportError(e, 'Не удалось загрузить счета') })
      })
    return () => controller.abort()
  }, [accountsKey])

  const accountList = accounts.status === 'ok' ? accounts.data : []
  const account = accountList.find((candidate) => candidate.wallet_id === state.wallet) ?? accountList[0] ?? null
  const types = TYPE_ORDER.filter((type) => accountList.some((candidate) => candidate.wallet_type === type))
  const sameType = accountList.filter((candidate) => candidate.wallet_type === account?.wallet_type)
  const query = account ? toBalancesQuery({ ...state, wallet: account.wallet_id }) : null
  const queryKey = query ? `${query.wallet}|${query.dateFrom ?? ''}|${query.dateTo}` : ''

  useEffect(() => {
    if (!query) return
    const controller = new AbortController()
    setLoading(true)
    setError(null)
    getAccountBalances(query, controller.signal)
      .then((data) => setLastData(data))
      .catch((e: unknown) => {
        if (!controller.signal.aborted) setError(describeReportError(e, 'Не удалось построить отчёт'))
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    return () => controller.abort()
    // queryKey stands for the query; the object itself is new on every render.
  }, [queryKey, reloadKey])

  const update = (patch: Partial<BalancesUrlState>) => setParams(writeBalancesState(params, { ...state, ...patch }), { replace: true })
  const range = useMemo<[Dayjs, Dayjs]>(() => [dayjs(state.start), dayjs(state.end)], [state.start, state.end])

  const exportExcel = async () => {
    if (!query) return
    setExporting(true)
    try {
      saveFile(await downloadAccountBalancesXlsx(query))
    } catch (e: unknown) {
      notifyApiError(describeReportError(e, 'Не удалось выгрузить Excel'))
    } finally {
      setExporting(false)
    }
  }

  if (accounts.status === 'loading') return <Skeleton active />
  if (accounts.status === 'error') {
    return (
      <Result
        status="warning"
        title="Счета не загрузились"
        subTitle={accounts.message}
        extra={<Button onClick={() => setAccountsKey((key) => key + 1)}>Повторить</Button>}
      />
    )
  }
  if (!account) {
    return (
      <Empty description="Нет доступных счетов. Здесь показываются счета банка, кассы и корпоративной карты, если у вас есть доступ к этим разделам." />
    )
  }

  // Another account's report never stays under this account's selector, figures or currency.
  const shown = lastData && lastData.account.wallet_id === account.wallet_id ? lastData : null
  const currency = shown?.account.currency ?? account.currency
  return (
    <div className="balances-report">
      <div className="balances-toolbar">
        <Segmented<BalancesMode>
          value={state.mode}
          onChange={(mode) => update({ mode })}
          options={[
            { label: 'Период', value: 'period' },
            { label: 'На дату', value: 'date' },
          ]}
        />
        {state.mode === 'period' ? (
          <DatePicker.RangePicker
            value={range}
            format="DD.MM.YYYY"
            allowClear={false}
            disabledDate={(day) => day.isAfter(dayjs(), 'day')}
            onChange={(values) => {
              if (values?.[0] && values[1]) update({ start: values[0].format(ISO), end: values[1].format(ISO) })
            }}
          />
        ) : (
          <DatePicker
            value={dayjs(state.end)}
            format="DD.MM.YYYY"
            allowClear={false}
            disabledDate={(day) => day.isAfter(dayjs(), 'day')}
            onChange={(value) => {
              if (value) update({ end: value.format(ISO) })
            }}
          />
        )}
        {types.length > 1 ? (
          <Segmented<BalanceAccountType>
            value={account.wallet_type}
            onChange={(type) => update({ wallet: accountList.find((candidate) => candidate.wallet_type === type)?.wallet_id ?? null })}
            options={types.map((type) => ({
              value: type,
              label: accountList.find((candidate) => candidate.wallet_type === type)?.type_label ?? type,
            }))}
          />
        ) : null}
        <Select<number>
          value={account.wallet_id}
          onChange={(wallet) => update({ wallet })}
          style={{ minWidth: 220 }}
          aria-label="Счёт"
          options={sameType.map((candidate) => ({ value: candidate.wallet_id, label: accountLabel(candidate) }))}
        />
        <Space className="balances-toolbar-end">
          <Button icon={<ReloadOutlined />} aria-label="Обновить" onClick={() => setReloadKey((key) => key + 1)} />
          <Button icon={<DownloadOutlined />} loading={exporting} onClick={() => void exportExcel()}>
            Excel
          </Button>
        </Space>
      </div>

      {error ? (
        <Alert
          type="error"
          showIcon
          message={error}
          action={<Button onClick={() => setReloadKey((key) => key + 1)}>Повторить</Button>}
          style={{ marginBottom: 16 }}
        />
      ) : null}

      {shown ? (
        <>
          <Typography.Paragraph type="secondary" style={{ marginBottom: 12 }}>
            {shown.account.type_label} · {accountLabel(shown.account)}
            {shown.account.account_no ? ` · ${shown.account.account_no}` : ''} · {formatDate(shown.date_from)} –{' '}
            {formatDate(shown.date_to)}
            {shown.since_first_operation ? ' (с первой операции)' : ''} · {countLabel(shown.operations_count)}
          </Typography.Paragraph>
          <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
            <Col xs={12} lg={6}>
              <Kpi label="Остаток на начало" value={shown.opening} currency={currency} />
            </Col>
            <Col xs={12} lg={6}>
              <Kpi label="Приход" value={shown.income} currency={currency} tone="success" />
            </Col>
            <Col xs={12} lg={6}>
              <Kpi label="Расход" value={shown.expense} currency={currency} tone="danger" />
            </Col>
            <Col xs={12} lg={6}>
              <Kpi label="Остаток на конец" value={shown.closing} currency={currency} />
            </Col>
          </Row>
          {shown.unconfirmed.count > 0 ? (
            <Alert
              type="warning"
              showIcon
              style={{ marginBottom: 16 }}
              message={`Не подтверждено: ${countLabel(shown.unconfirmed.count)}`}
              description={`Они показаны в списке, но не входят в остатки: приход ${balanceAmount(shown.unconfirmed.income)}, расход ${balanceAmount(shown.unconfirmed.expense)} ${currency}. Частая причина расхождения с банком.`}
            />
          ) : null}
        </>
      ) : null}

      {shown || loading ? (
        <BalanceDaysTableWidget
          // A new account or period starts with every day collapsed and on the first page.
          key={shown ? `${shown.account.wallet_id}|${shown.date_from}|${shown.date_to}` : 'loading'}
          days={shown?.days ?? []}
          loading={loading}
        />
      ) : null}

      <Typography.Paragraph type="secondary" style={{ marginTop: 12, fontSize: 12 }}>
        Остатки считаются так же, как на страницах Банк, Касса и Корпоративная карта: от начального остатка счёта на
        {formatDate(shown?.opening_balance_day ?? `${dayjs().year()}-01-01`)} плюс приходы и минус расходы; банк — по дате
        документа. Раскройте день, чтобы увидеть
        операции и остаток после каждой.
      </Typography.Paragraph>
    </div>
  )
}
