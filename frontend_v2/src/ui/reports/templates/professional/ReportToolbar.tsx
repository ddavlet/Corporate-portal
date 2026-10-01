import { FileExcelOutlined, LinkOutlined, MoreOutlined } from '@ant-design/icons'
import { Button, Dropdown, Segmented, Select, Switch, type MenuProps } from 'antd'
import dayjs from 'dayjs'
import type { StatementMeta, StatementPeriod } from '../../../../lib/reportsApi'
import { MONTH_NAMES, type Units } from '../../../../lib/reportsFormat'
import { effectiveMonth, effectiveYear, type ReportUrlState, type ReportView } from './useReportUrlState'

type Props = {
  state: ReportUrlState
  update: (patch: Partial<ReportUrlState>) => void
  meta: StatementMeta | null
  isAdmin: boolean
  onCopyLink: () => void
  exporting: boolean
  onExportExcel: () => void
  onPrint: () => void
  onOpenMethodology: () => void
  /** Opens the rules drawer of this report; null hides «Настройки отчёта». */
  onOpenRules: (() => void) | null
  onOpenTemplateSettings: () => void
}

const PERIOD_OPTIONS: { value: StatementPeriod; label: string }[] = [
  { value: 'month', label: 'Месяц' },
  { value: 'ytd', label: 'С начала года' },
  { value: 'year', label: 'Год' },
  { value: 'ltm', label: 'Последние 12 месяцев' },
]

function monthOptions(meta: StatementMeta | null): { value: string; label: string }[] {
  const today = meta ? dayjs(meta.today) : dayjs()
  const start = meta ? dayjs(`${meta.start_month}-01`) : today.subtract(24, 'month')
  const out: { value: string; label: string }[] = []
  let cursor = today.startOf('month')
  for (let guard = 0; guard < 120 && !cursor.isBefore(start, 'month'); guard += 1) {
    out.push({ value: cursor.format('YYYY-MM'), label: `${MONTH_NAMES[cursor.month()]} ${cursor.year()}` })
    cursor = cursor.subtract(1, 'month')
  }
  return out
}

function yearOptions(meta: StatementMeta | null): { value: number; label: string }[] {
  const current = meta ? dayjs(meta.today).year() : dayjs().year()
  const first = meta ? Number(meta.start_month.slice(0, 4)) : current - 2
  const out: { value: number; label: string }[] = []
  for (let year = current; year >= Math.min(first, current); year -= 1) out.push({ value: year, label: String(year) })
  return out
}

export function ReportToolbar({
  state,
  update,
  meta,
  isAdmin,
  onCopyLink,
  exporting,
  onExportExcel,
  onPrint,
  onOpenMethodology,
  onOpenRules,
  onOpenTemplateSettings,
}: Props) {
  const menuItems: MenuProps['items'] = [
    { key: 'method', label: 'Как считается отчёт' },
    // Print lays out the statement card only; the operations list has no print layout.
    ...(state.view === 'statement' ? [{ key: 'print', label: 'Печать' }] : []),
    ...(onOpenRules ? [{ key: 'rules', label: 'Настройки отчёта' }] : []),
    ...(isAdmin ? [{ key: 'templates', label: 'Шаблоны отчётов' }] : []),
  ]
  const actions: Record<string, () => void> = {
    method: onOpenMethodology,
    print: onPrint,
    rules: () => onOpenRules?.(),
    templates: onOpenTemplateSettings,
  }
  return (
    <div className="rp-toolbar">
      <div className="rp-toolbar-row">
        <div className="rp-toolbar-spacer" />
        <Button icon={<LinkOutlined />} onClick={onCopyLink}>
          Ссылка
        </Button>
        <Button icon={<FileExcelOutlined />} loading={exporting} onClick={onExportExcel}>
          Excel
        </Button>
        <Dropdown trigger={['click']} menu={{ items: menuItems, onClick: ({ key }) => actions[key]?.() }}>
          <Button icon={<MoreOutlined />} aria-label="Ещё" />
        </Dropdown>
      </div>
      <div className="rp-toolbar-row">
        <Select
          aria-label="Период"
          style={{ width: 210 }}
          value={state.period}
          onChange={(value: StatementPeriod) => update({ period: value, drill: null })}
          options={PERIOD_OPTIONS}
        />
        {state.period === 'month' ? (
          <Select
            aria-label="Месяц"
            style={{ width: 190 }}
            value={effectiveMonth(state, meta ? dayjs(meta.today) : dayjs())}
            onChange={(value: string) => update({ month: value, drill: null })}
            options={monthOptions(meta)}
          />
        ) : null}
        {state.period === 'year' ? (
          <Select
            aria-label="Год"
            style={{ width: 120 }}
            value={effectiveYear(state, meta ? dayjs(meta.today) : dayjs())}
            onChange={(value: number) => update({ year: value, drill: null })}
            options={yearOptions(meta)}
          />
        ) : null}
        {state.period !== 'month' ? (
          <Segmented
            aria-label="Колонки"
            value={state.granularity}
            onChange={(value) => update({ granularity: String(value) === 'quarter' ? 'quarter' : 'month', drill: null })}
            options={[
              { label: 'Месяцы', value: 'month' },
              { label: 'Кварталы', value: 'quarter' },
            ]}
          />
        ) : null}
        {state.period !== 'month' ? (
          <label className="rp-switch">
            <Switch size="small" checked={state.compare === 'yoy'} onChange={(on) => update({ compare: on ? 'yoy' : 'none' })} />
            Сравнить с прошлым годом
          </label>
        ) : null}
        <div className="rp-toolbar-spacer" />
        <Segmented
          aria-label="Единицы"
          value={state.units}
          onChange={(value) => update({ units: String(value) as Units })}
          options={[
            { label: 'сум', value: 'sum' },
            { label: 'тыс.', value: 'k' },
            { label: 'млн', value: 'm' },
          ]}
        />
        <Segmented
          aria-label="Вид"
          value={state.view}
          onChange={(value) => update({ view: String(value) as ReportView, drill: null })}
          options={[
            { label: 'Отчёт', value: 'statement' },
            { label: 'Операции', value: 'operations' },
          ]}
        />
      </div>
    </div>
  )
}
