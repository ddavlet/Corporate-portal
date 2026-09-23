import { InfoCircleOutlined, ReloadOutlined } from '@ant-design/icons'
import { Alert, Button, Grid, Result, Segmented, Skeleton, Tag } from 'antd'
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError } from '../../../../lib/api'
import { notifyApiError, notifyApiSuccess } from '../../../../lib/apiNotify'
import {
  downloadStatementXlsx,
  getStatement,
  type StatementColumn,
  type StatementQuery,
  type StatementResponse,
} from '../../../../lib/reportsApi'
import { describeReportError } from '../../../../lib/reportErrors'
import { formatDate, UNITS_LABEL } from '../../../../lib/reportsFormat'
import { saveFile } from '../../../../lib/saveFile'
import { useTenantAdmin } from '../../../../lib/useTenantAdmin'
import { useUserPreference } from '../../../../lib/useUserPreference'
import type { ReportTemplateProps } from '../types'
import { DataWarningBanner } from './DataWarningBanner'
import { defaultOpenGroups } from './flattenStatementRows'
import { KpiStripWidget } from './KpiStripWidget'
import { MethodologyDrawer } from './MethodologyDrawer'
import { phoneChipOptions, phoneColumnKeys, resolvePhoneColumnKey } from './phoneColumns'
import { REPORT_SETTINGS_PATHS, ReportToolbar } from './ReportToolbar'
import { useRequestPreview } from './RequestPreview'
import { StatementDrilldownDrawer, type DrillRequest } from './StatementDrilldownDrawer'
import { StatementTableWidget } from './StatementTableWidget'
import { TransactionsWidget } from './TransactionsWidget'
import { TrendChartWidget } from './TrendChartWidget'
import { toStatementQuery, useReportUrlState, type DrillTarget } from './useReportUrlState'
import './professional.css'

const TEMPLATE_KEY = 'professional'
const TITLES = { pnl: 'Отчёт о прибылях и убытках', cashflow: 'Отчёт о движении денежных средств' } as const
const NAMES = { pnl: 'Прибыли и убытки', cashflow: 'Движение денег' } as const

/** The range the headline numbers describe: the period total, or the reporting month in a monthly report. */
function mainColumn(statement: StatementResponse): StatementColumn | undefined {
  return statement.columns.find((column) => column.key === 'total') ?? statement.columns.find((column) => column.kind === 'period')
}

function drillRequest(statement: StatementResponse, drill: DrillTarget | null): DrillRequest | null {
  if (!drill) return null
  const row = statement.rows.find((candidate) => candidate.id === drill.line && candidate.drillable)
  const candidates = statement.columns.filter((candidate) => candidate.kind !== 'delta')
  // A link to the unfinished month keeps working after that month has grown: same start, still running.
  const column =
    candidates.find((candidate) => candidate.from === drill.from && candidate.to === drill.to) ??
    candidates.find(
      (candidate) => candidate.from === drill.from && candidate.partial && candidate.to !== null && candidate.to >= drill.to,
    )
  if (!row || !column) return null
  const byId = new Map(statement.rows.map((candidate) => [candidate.id, candidate]))
  const ancestors: string[] = []
  for (let parent = row.parent; parent; parent = byId.get(parent)?.parent ?? null) {
    const found = byId.get(parent)
    if (!found) break
    ancestors.unshift(found.label)
  }
  return { template: TEMPLATE_KEY, report: statement.report, row, column, crumbs: [NAMES[statement.report], ...ancestors] }
}

/** The copied link names the template, so the recipient sees this view even when their own default is another one. */
function shareableHref(): string {
  const url = new URL(window.location.href)
  url.searchParams.set('t', TEMPLATE_KEY)
  return url.toString()
}

function isNotConfigured(error: Error | null): error is ApiError {
  return error instanceof ApiError && error.status === 503
}

function LoadError({ error, isAdmin, onRetry, onOpenSettings }: { error: Error | null; isAdmin: boolean; onRetry: () => void; onOpenSettings: () => void }) {
  if (isNotConfigured(error)) {
    return (
      <Result
        status="info"
        title="Отчёт не настроен"
        subTitle={
          <>
            <div>Настройки отчёта не заданы или содержат ошибку.</div>
            {/* The backend detail (settings rows, tenant ids) helps an admin fix it; others only need what to do. */}
            {isAdmin ? <div className="rp-muted">{`Подробности: ${error.message}`}</div> : null}
          </>
        }
        extra={
          isAdmin ? (
            <Button type="primary" onClick={onOpenSettings}>
              Настроить отчёт
            </Button>
          ) : (
            <span>Обратитесь к администратору компании.</span>
          )
        }
      />
    )
  }
  return (
    <Alert
      type="error"
      showIcon
      message={error?.message ?? 'Не удалось загрузить отчёт'}
      action={
        <Button size="small" onClick={onRetry}>
          Повторить
        </Button>
      }
    />
  )
}

export function ProfessionalReportTemplate({ templateSwitcher }: ReportTemplateProps) {
  const navigate = useNavigate()
  const [state, update] = useReportUrlState()
  const { isAdmin } = useTenantAdmin()
  const chartPreference = useUserPreference<boolean>({
    key: 'reports.chart.collapsed.v1',
    defaultValue: false,
    normalize: (raw) => raw === true,
  })
  const preview = useRequestPreview()
  // The statement remembers which query it answers, so an error for another query never sits next to old numbers.
  const [loaded, setLoaded] = useState<{ key: string; statement: StatementResponse } | null>(null)
  const statement = loaded?.statement ?? null
  const [error, setError] = useState<Error | null>(null)
  const [loading, setLoading] = useState(true)
  const [reloadKey, setReloadKey] = useState(0)
  const refreshNext = useRef(false)
  const [methodologyOpen, setMethodologyOpen] = useState(false)
  const [exporting, setExporting] = useState(false)
  // Phones (below antd's md breakpoint, as in AppShell): one period column at a time, panels full screen.
  const isPhone = !Grid.useBreakpoint().md
  // A chip choice belongs to one query: a new report or period starts again on its latest period.
  const [phoneChoice, setPhoneChoice] = useState<{ query: string; column: string } | null>(null)

  // Only the fields that change the numbers trigger a reload; open groups, units, view and drill-down do not.
  const queryKey = JSON.stringify(toStatementQuery(TEMPLATE_KEY, state))

  useEffect(() => {
    const controller = new AbortController()
    const refresh = refreshNext.current
    refreshNext.current = false
    setLoading(true)
    setError(null)
    getStatement({ ...(JSON.parse(queryKey) as StatementQuery), refresh }, controller.signal)
      .then((data) => setLoaded({ key: queryKey, statement: data }))
      .catch((e: unknown) => {
        if ((e as { name?: string } | null)?.name === 'AbortError') return
        setError(e instanceof ApiError ? e : new Error(describeReportError(e, 'Не удалось загрузить отчёт')))
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    return () => controller.abort()
  }, [queryKey, reloadKey])

  const reload = (withRefresh: boolean) => {
    refreshNext.current = withRefresh
    setReloadKey((key) => key + 1)
  }

  const settingsPath = REPORT_SETTINGS_PATHS[state.report]

  const copyLink = async () => {
    const href = shareableHref()
    try {
      await navigator.clipboard.writeText(href)
      notifyApiSuccess('Ссылка скопирована')
    } catch {
      // Clipboard blocked (permissions, insecure context): let the user copy the link by hand.
      window.prompt('Скопируйте ссылку', href)
    }
  }

  const exportExcel = async () => {
    setExporting(true)
    try {
      saveFile(await downloadStatementXlsx({ ...toStatementQuery(TEMPLATE_KEY, state), units: state.units }))
    } catch (e: unknown) {
      notifyApiError(describeReportError(e, 'Не удалось выгрузить Excel'))
    } finally {
      setExporting(false)
    }
  }

  const toolbar = (
    <ReportToolbar
      state={state}
      update={update}
      meta={statement?.meta ?? null}
      isAdmin={isAdmin}
      templateSwitcher={templateSwitcher}
      onCopyLink={() => void copyLink()}
      exporting={exporting}
      onExportExcel={() => void exportExcel()}
      onPrint={() => window.print()}
      onOpenMethodology={() => setMethodologyOpen(true)}
      onOpenSettings={(path) => navigate(path)}
    />
  )

  // Previous numbers may stay (dimmed) while the next query loads, but not once it has failed or when the report is not configured.
  const showLoadError = error !== null && (loaded === null || loaded.key !== queryKey || isNotConfigured(error))
  if (!statement || showLoadError) {
    return (
      <div className="rp-page">
        {toolbar}
        {showLoadError ? (
          <LoadError error={error} isAdmin={isAdmin} onRetry={() => reload(false)} onOpenSettings={() => navigate(settingsPath)} />
        ) : (
          <Skeleton active />
        )}
      </div>
    )
  }

  const open = new Set(state.open ?? defaultOpenGroups(statement.rows))
  const toggle = (rowId: string) => {
    const next = new Set(open)
    if (next.has(rowId)) next.delete(rowId)
    else next.add(rowId)
    update({ open: [...next] })
  }
  const drill = drillRequest(statement, state.drill)
  const main = mainColumn(statement)
  const partial = statement.columns.find((column) => column.kind === 'period' && column.partial)
  const phoneColumn = phoneChoice?.query === queryKey ? phoneChoice.column : null
  const phoneKeys = isPhone ? phoneColumnKeys(statement.columns, phoneColumn) : undefined
  const chipOptions = phoneChipOptions(statement.columns)
  const phoneChips = isPhone && chipOptions.length > 1

  return (
    <div className={`rp-page${loading ? ' is-loading' : ''}`}>
      {toolbar}
      {error ? (
        <Alert
          type="error"
          showIcon
          message={error.message}
          action={
            <Button size="small" onClick={() => reload(false)}>
              Повторить
            </Button>
          }
        />
      ) : null}
      <DataWarningBanner warnings={statement.warnings} units={state.units} isAdmin={isAdmin} onOpenSettings={() => navigate(settingsPath)} />
      <KpiStripWidget kpis={statement.kpis} units={state.units} />
      <TrendChartWidget
        chart={statement.chart}
        units={state.units}
        report={statement.report}
        collapsed={chartPreference.value}
        onToggle={() => chartPreference.setValue(!chartPreference.value)}
      />
      {state.view === 'statement' ? (
        <section className="rp-card rp-print-area">
          <div className="rp-print-header">
            <strong>{statement.meta.company ?? ''}</strong>
            <div>
              {`${TITLES[statement.report]} · ${statement.meta.period_label}${
                main?.from && main.to ? ` (${formatDate(main.from)} – ${formatDate(main.to)})` : ''
              }`}
            </div>
            <div>
              {`${UNITS_LABEL[state.units]} · данные на ${formatDate(statement.meta.generated_at.slice(0, 10))} ${statement.meta.generated_at.slice(11, 16)}`}
            </div>
          </div>
          <header className="rp-card-head rp-no-print">
            <div>
              <h3>{TITLES[statement.report]}</h3>
              <small>
                {`${statement.meta.period_label} · ${UNITS_LABEL[state.units]}${statement.meta.company ? ` · ${statement.meta.company}` : ''}`}
              </small>
            </div>
            <div className="rp-legend">
              {statement.meta.source === 'n8n' ? <Tag>источник: n8n</Tag> : null}
              <span>{`обновлено ${statement.meta.generated_at.slice(11, 16)}`}</span>
              <Button type="text" size="small" icon={<ReloadOutlined />} aria-label="Обновить данные" onClick={() => reload(true)} />
              <Button type="link" size="small" icon={<InfoCircleOutlined />} onClick={() => setMethodologyOpen(true)}>
                Как считается
              </Button>
            </div>
          </header>
          {phoneChips ? (
            <div className="rp-phone-periods rp-no-print">
              <Segmented
                aria-label="Период таблицы"
                value={resolvePhoneColumnKey(statement.columns, phoneColumn) ?? undefined}
                onChange={(value) => setPhoneChoice({ query: queryKey, column: String(value) })}
                options={chipOptions}
              />
            </div>
          ) : null}
          <StatementTableWidget
            statement={statement}
            columnKeys={phoneKeys}
            compact={isPhone}
            units={state.units}
            open={open}
            selected={drill ? { rowId: drill.row.id, columnKey: drill.column.key } : null}
            onToggle={toggle}
            onDrill={(rowId, column) => {
              if (column.from && column.to) update({ drill: { line: rowId, from: column.from, to: column.to } })
            }}
          />
          <footer className="rp-foot">
            {partial ? <span>{`* ${partial.label.replace('*', '')}: период не закрыт, данные по ${formatDate(partial.to)}.`}</span> : null}
            <span className="rp-no-print">Нажмите на сумму, чтобы увидеть операции.</span>
          </footer>
        </section>
      ) : main?.from && main.to ? (
        <TransactionsWidget
          template={TEMPLATE_KEY}
          report={statement.report}
          from={main.from}
          to={main.to}
          rows={statement.rows}
          onOpenRequest={preview.open}
        />
      ) : null}
      <StatementDrilldownDrawer
        request={drill}
        onCopyLink={() => void copyLink()}
        units={state.units}
        fullScreen={isPhone}
        onClose={() => update({ drill: null })}
        onOpenRequest={preview.open}
      />
      <MethodologyDrawer
        open={methodologyOpen}
        rules={statement.methodology}
        fullScreen={isPhone}
        isAdmin={isAdmin}
        onClose={() => setMethodologyOpen(false)}
        onOpenSettings={() => navigate(settingsPath)}
      />
      {preview.modal}
    </div>
  )
}
