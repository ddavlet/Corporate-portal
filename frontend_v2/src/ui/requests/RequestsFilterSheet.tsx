import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Button, DatePicker, InputNumber, Select, Switch, Typography, theme } from 'antd'
import { CloseOutlined, RightOutlined } from '@ant-design/icons'
import dayjs, { type Dayjs } from 'dayjs'
import {
  getRequestCategories,
  getRequestFormOptions,
  getRequestVendors,
  type RequestCategoryOption,
  type RequestFormOptionsRequester,
} from '../../lib/api'
import { MOBILE_STATUS_OPTIONS } from '../../lib/requestStatusLabels'
import { requestPaymentTypeSelectOptions, withoutInvestTypesUnlessEnabled } from '../../lib/requestPaymentTypes'
import { useInvestmentFundingMode } from '../../lib/useInvestmentFundingMode'
import { MobileSheet } from '../MobileSheet'
import { MobilePickerSheet, PICKER_PAGE_SIZE } from '../MobilePickerSheet'
import { clearFilters, type MobileRequestsFilters, type RequestsTab } from './requestsListQuery'

/** The same choices as the desktop filter panel. */
const PAYMENT_TYPE_OPTIONS = requestPaymentTypeSelectOptions()
const URGENCY_OPTIONS = ['Низко', 'Обычно', 'Срочно'].map((value) => ({ value, label: value }))
const CURRENCY_OPTIONS = ['UZS', 'USD', 'EUR', 'RUB'].map((value) => ({ value, label: value }))

const DAY = 'YYYY-MM-DD'

type Range = { from?: string; to?: string }
type Preset = { key: string; label: string; range: () => Range }

const SUBMITTED_PRESETS: Preset[] = [
  { key: 'today', label: 'Сегодня', range: () => ({ from: dayjs().format(DAY), to: dayjs().format(DAY) }) },
  { key: 'week', label: '7 дней', range: () => ({ from: dayjs().subtract(6, 'day').format(DAY), to: dayjs().format(DAY) }) },
  {
    key: 'month',
    label: 'Этот месяц',
    range: () => ({ from: dayjs().startOf('month').format(DAY), to: dayjs().endOf('month').format(DAY) }),
  },
  {
    key: 'prev-month',
    label: 'Прошлый месяц',
    range: () => {
      const prev = dayjs().subtract(1, 'month')
      return { from: prev.startOf('month').format(DAY), to: prev.endOf('month').format(DAY) }
    },
  },
]

const BILLING_PRESETS: Preset[] = SUBMITTED_PRESETS.filter((preset) => preset.key === 'month' || preset.key === 'prev-month')

function parseDay(value: string | undefined): Dayjs | null {
  if (!value) return null
  const parsed = dayjs(value)
  return parsed.isValid() ? parsed : null
}

type Props = {
  open: boolean
  tab: RequestsTab
  /** Filters applied to the feed; the sheet edits a copy and hands it back on «Показать». */
  value: MobileRequestsFilters
  onClose: () => void
  onApply: (filters: MobileRequestsFilters) => void
}

/**
 * Bottom sheet with every filter of the desktop panel: status, type, urgency and currency as chips, category and
 * requester lists, the vendor on a full-screen search, amounts, dates with presets and the two switches. Nothing reaches
 * the feed until «Показать»; «Сбросить» clears the sheet.
 */
export function RequestsFilterSheet({ open, tab, value, onClose, onApply }: Props) {
  const { token } = theme.useToken()
  const [draft, setDraft] = useState<MobileRequestsFilters>(value)
  const [vendorPickerOpen, setVendorPickerOpen] = useState(false)
  const [categories, setCategories] = useState<RequestCategoryOption[]>([])
  const [requesters, setRequesters] = useState<RequestFormOptionsRequester[]>([])
  const [optionsRequested, setOptionsRequested] = useState(false)
  const vendorsRef = useRef<Promise<string[]> | null>(null)
  const investmentMode = useInvestmentFundingMode(optionsRequested)

  // Every opening starts from what the feed shows now; while the sheet is open the draft does not follow the feed.
  const valueRef = useRef(value)
  useEffect(() => {
    valueRef.current = value
  }, [value])
  useEffect(() => {
    if (open) setDraft(valueRef.current)
  }, [open])

  // Directories are asked for once, on the first opening.
  useEffect(() => {
    if (open && !optionsRequested) setOptionsRequested(true)
  }, [open, optionsRequested])

  useEffect(() => {
    if (!optionsRequested) return
    let cancelled = false
    getRequestCategories()
      .then((rows) => {
        if (!cancelled) setCategories(rows)
      })
      .catch(() => undefined)
    getRequestFormOptions()
      .then((options) => {
        if (!cancelled) setRequesters(options.requester_candidates ?? [])
      })
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [optionsRequested])

  const paymentTypeOptions = useMemo(
    () => withoutInvestTypesUnlessEnabled(PAYMENT_TYPE_OPTIONS, (option) => option.value, investmentMode),
    [investmentMode],
  )

  const loadVendors = (search: string): Promise<string[]> => {
    if (!vendorsRef.current) {
      vendorsRef.current = getRequestVendors().catch((error: unknown) => {
        vendorsRef.current = null
        throw error
      })
    }
    const needle = search.trim().toLowerCase()
    return vendorsRef.current.then((all) =>
      all.filter((name) => !needle || name.toLowerCase().includes(needle)).slice(0, PICKER_PAGE_SIZE),
    )
  }

  const patch = (next: Partial<MobileRequestsFilters>) => setDraft((prev) => ({ ...prev, ...next }))

  const showRequester = tab !== 'my' && requesters.length > 0

  return (
    <>
      <MobileSheet
        open={open}
        onClose={onClose}
        title="Фильтры"
        footer={
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
            <Button onClick={() => setDraft(clearFilters(draft, true))}>Сбросить</Button>
            <Button type="primary" onClick={() => onApply(draft)}>
              Показать
            </Button>
          </div>
        }
      >
        <div style={{ display: 'grid', gap: 20 }}>
          {tab !== 'drafts' ? (
            <Section title="Статус">
              <ChipGroup
                label="Статус"
                options={MOBILE_STATUS_OPTIONS}
                value={draft.status}
                onChange={(status) => patch({ status })}
              />
            </Section>
          ) : null}

          <Section title="Тип оплаты">
            <ChipGroup
              label="Тип оплаты"
              options={paymentTypeOptions}
              value={draft.paymentType}
              onChange={(paymentType) => patch({ paymentType })}
            />
          </Section>

          <Section title="Срочность">
            <ChipGroup label="Срочность" options={URGENCY_OPTIONS} value={draft.urgency} onChange={(urgency) => patch({ urgency })} />
          </Section>

          <Section title="Валюта">
            <ChipGroup label="Валюта" options={CURRENCY_OPTIONS} value={draft.currency} onChange={(currency) => patch({ currency })} />
          </Section>

          <Section title="Категория" htmlFor="requests-filter-category">
            <Select
              id="requests-filter-category"
              aria-label="Категория"
              placeholder="Любая"
              allowClear
              showSearch
              optionFilterProp="label"
              value={draft.category}
              onChange={(category?: string) => patch({ category: category || undefined })}
              options={categories.map((c) => ({ value: c.name, label: c.name }))}
              style={{ width: '100%' }}
            />
          </Section>

          <Section title="Поставщик">
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <button
                type="button"
                className="m-list-row"
                aria-label={draft.vendor ? `Поставщик: ${draft.vendor}` : 'Поставщик: любой'}
                onClick={() => setVendorPickerOpen(true)}
                style={{
                  flex: 1,
                  minWidth: 0,
                  border: `1px solid ${token.colorBorder}`,
                  borderRadius: token.borderRadius,
                  padding: '10px 12px',
                }}
              >
                <span className="m-ellipsis" style={{ flex: 1, color: draft.vendor ? token.colorText : token.colorTextPlaceholder }}>
                  {draft.vendor || 'Любой'}
                </span>
                <RightOutlined aria-hidden />
              </button>
              {draft.vendor ? (
                <Button
                  type="text"
                  icon={<CloseOutlined />}
                  aria-label="Убрать поставщика"
                  onClick={() => patch({ vendor: undefined })}
                  style={{ width: 44, flexShrink: 0 }}
                />
              ) : null}
            </div>
          </Section>

          {showRequester ? (
            <Section title="Заявитель" htmlFor="requests-filter-requester">
              <Select
                id="requests-filter-requester"
                aria-label="Заявитель"
                placeholder="Любой"
                allowClear
                showSearch
                optionFilterProp="label"
                value={draft.requester}
                onChange={(requester?: string) => {
                  const picked = requesters.find((r) => String(r.id) === requester)
                  patch({ requester: requester || undefined, requesterName: picked?.username })
                }}
                options={requesters.map((r) => ({ value: String(r.id), label: r.username }))}
                style={{ width: '100%' }}
              />
            </Section>
          ) : null}

          <Section title="Сумма">
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
              <InputNumber
                aria-label="Сумма от"
                placeholder="от"
                min={0}
                inputMode="decimal"
                value={draft.amountMin}
                onChange={(amountMin) => patch({ amountMin: typeof amountMin === 'number' ? amountMin : null })}
                style={{ width: '100%' }}
              />
              <InputNumber
                aria-label="Сумма до"
                placeholder="до"
                min={0}
                inputMode="decimal"
                value={draft.amountMax}
                onChange={(amountMax) => patch({ amountMax: typeof amountMax === 'number' ? amountMax : null })}
                style={{ width: '100%' }}
              />
            </div>
          </Section>

          <Section title="Дата отправки">
            <RangeField
              label="Дата отправки"
              presets={SUBMITTED_PRESETS}
              range={{ from: draft.submittedFrom, to: draft.submittedTo }}
              onChange={({ from, to }) => patch({ submittedFrom: from, submittedTo: to })}
            />
          </Section>

          <Section title="Месяц биллинга">
            <RangeField
              label="Месяц биллинга"
              month
              presets={BILLING_PRESETS}
              range={{ from: draft.billingFrom, to: draft.billingTo }}
              onChange={({ from, to }) => patch({ billingFrom: from, billingTo: to })}
            />
          </Section>

          <div style={{ display: 'grid', gap: 12 }}>
            <SwitchRow
              label="Только с амортизацией"
              checked={draft.amortizedOnly}
              onChange={(amortizedOnly) => patch({ amortizedOnly })}
            />
            <SwitchRow
              label="Оплачена без расхода"
              checked={draft.payedMissingExpense}
              onChange={(payedMissingExpense) => patch({ payedMissingExpense })}
            />
          </div>
        </div>
      </MobileSheet>

      {/* A sibling of the sheet, not inside it: the sheet stays as it was underneath and keeps the other fields. */}
      <MobilePickerSheet<string>
        open={vendorPickerOpen}
        title="Поставщик"
        onClose={() => setVendorPickerOpen(false)}
        load={loadVendors}
        getKey={(name) => name}
        renderItem={(name) => name}
        selectedKey={draft.vendor ?? null}
        searchPlaceholder="Поиск поставщика"
        onSelect={(vendor) => {
          patch({ vendor })
          setVendorPickerOpen(false)
        }}
      />
    </>
  )
}

function Section({ title, htmlFor, children }: { title: string; htmlFor?: string; children: ReactNode }) {
  const { token } = theme.useToken()
  const style = { display: 'block', marginBottom: 8, fontWeight: 600, color: token.colorText }
  return (
    <section style={{ minWidth: 0 }}>
      {htmlFor ? (
        <label htmlFor={htmlFor} style={style}>
          {title}
        </label>
      ) : (
        <Typography.Text style={style}>{title}</Typography.Text>
      )}
      {children}
    </section>
  )
}

type ChipOption = { value: string; label: string }

/** Single choice as chips: a second tap on the chosen chip clears it. */
function ChipGroup({
  label,
  options,
  value,
  onChange,
}: {
  label: string
  options: ReadonlyArray<ChipOption>
  value: string | undefined
  onChange: (value: string | undefined) => void
}) {
  return (
    <div role="group" aria-label={label} style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
      {options.map((option) => {
        const active = option.value === value
        return (
          <Button
            key={option.value}
            shape="round"
            type={active ? 'primary' : 'default'}
            aria-pressed={active}
            onClick={() => onChange(active ? undefined : option.value)}
          >
            {option.label}
          </Button>
        )
      })}
    </div>
  )
}

/** Presets as chips, then «с» and «по» in two columns (days, or months for billing). */
function RangeField({
  label,
  presets,
  range,
  onChange,
  month = false,
}: {
  label: string
  presets: Preset[]
  range: Range
  onChange: (range: Range) => void
  month?: boolean
}) {
  const activePreset = presets.find((preset) => {
    const candidate = preset.range()
    return candidate.from === range.from && candidate.to === range.to
  })
  const fromValue = parseDay(range.from)
  const toValue = parseDay(range.to)

  return (
    <div style={{ display: 'grid', gap: 8 }}>
      <ChipGroup
        label={`${label}: быстрый выбор`}
        options={presets.map((preset) => ({ value: preset.key, label: preset.label }))}
        value={activePreset?.key}
        onChange={(key) => {
          const preset = presets.find((p) => p.key === key)
          onChange(preset ? preset.range() : {})
        }}
      />
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
        <DatePicker
          aria-label={`${label} с`}
          placeholder="с"
          picker={month ? 'month' : 'date'}
          format={month ? 'MM.YYYY' : 'DD.MM.YYYY'}
          inputReadOnly
          value={fromValue}
          onChange={(next: Dayjs | null) =>
            onChange({ ...range, from: next ? (month ? next.startOf('month') : next).format(DAY) : undefined })
          }
          style={{ width: '100%' }}
        />
        <DatePicker
          aria-label={`${label} по`}
          placeholder="по"
          picker={month ? 'month' : 'date'}
          format={month ? 'MM.YYYY' : 'DD.MM.YYYY'}
          inputReadOnly
          value={toValue}
          onChange={(next: Dayjs | null) =>
            onChange({ ...range, to: next ? (month ? next.endOf('month') : next).format(DAY) : undefined })
          }
          style={{ width: '100%' }}
        />
      </div>
    </div>
  )
}

function SwitchRow({ label, checked, onChange }: { label: string; checked: boolean; onChange: (checked: boolean) => void }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, minHeight: 44 }}>
      <span aria-hidden>{label}</span>
      <Switch checked={checked} onChange={onChange} aria-label={label} />
    </div>
  )
}
