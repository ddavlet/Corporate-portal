import { useEffect, useMemo, useRef, useState } from 'react'
import { Alert, Button, Card, Collapse, DatePicker, Input, InputNumber, Modal, Select, Skeleton, Space, Switch, Table, Tag, Typography, message } from 'antd'
import type { ColumnsType, TableProps } from 'antd/es/table'
import type { Dayjs } from 'dayjs'
import dayjs from 'dayjs'
import { useNavigate } from 'react-router-dom'
import { CopyOutlined, FileAddOutlined, FileSearchOutlined, MessageOutlined, ReloadOutlined } from '@ant-design/icons'
import { apiFetch, copyPortalRequest, getRequestFormOptions, resendRequestApprovals } from '../../lib/api'
import { isPayedMissingLinkedExpense, type RequestExpenseLink } from '../../lib/requestExpense'
import { RequestDetailModal, type RequestDetail } from './RequestDetailModal'
import { NoteCreateModal } from '../NoteCreateModal'
import { useUserPreference } from '../../lib/useUserPreference'

type RequestRow = {
  id: number
  title: string
  description: string
  amount: number
  currency: string
  status: string
  urgency: string
  payment_type: string
  category: string
  vendor: string
  payment_purpose?: string
  file_link?: string | null
  requester: number | null
  requester_username?: string | null
  submitted_at: string
  billing_date: string
  expense_link?: RequestExpenseLink
  is_amortized?: boolean
  amortization_months?: number
}

type SortState = {
  field: keyof RequestRow | null
  order: 'ascend' | 'descend' | null
}

type RequestModalEditDraft = {
  title: string
  description: string
  amount: number | null
  currency: string
  status: string
  urgency: string
  payment_type: string
  category: string
  vendor: string
  payment_purpose: string
  billing_date: Dayjs | null
  requester: string
  amortization_enabled: boolean
  amortization_months: number
}

type RequestsPagePreferences = {
  search: string
  status?: string
  urgency?: string
  paymentType?: string
  currency?: string
  category?: string
  vendor?: string
  requester?: string
  amountMin: number | null
  amountMax: number | null
  submittedRange: [string | null, string | null] | null
  billingRange: [string | null, string | null] | null
  amortizedOnly: boolean
}

const REQUESTS_FILTER_PREF_KEY = 'requests.page.filters.v1'
const defaultRequestsPreferences: RequestsPagePreferences = {
  search: '',
  status: undefined,
  urgency: undefined,
  paymentType: undefined,
  currency: undefined,
  category: undefined,
  vendor: undefined,
  requester: undefined,
  amountMin: null,
  amountMax: null,
  submittedRange: null,
  billingRange: null,
  amortizedOnly: false,
}

function parseStoredRange(raw: [string | null, string | null] | null | undefined): [Dayjs | null, Dayjs | null] | null {
  if (!raw || !Array.isArray(raw)) return null
  const left = raw[0] ? dayjs(raw[0]) : null
  const right = raw[1] ? dayjs(raw[1]) : null
  return [left && left.isValid() ? left : null, right && right.isValid() ? right : null]
}

function serializeRange(value: [Dayjs | null, Dayjs | null] | null): [string | null, string | null] | null {
  if (!value) return null
  return [
    value[0] ? value[0].format('YYYY-MM-DD') : null,
    value[1] ? value[1].format('YYYY-MM-DD') : null,
  ]
}

function normalizeRows(payload: unknown): RequestRow[] {
  if (Array.isArray(payload)) return payload as RequestRow[]
  if (payload && typeof payload === 'object' && 'results' in payload) {
    const results = (payload as { results?: unknown }).results
    return Array.isArray(results) ? (results as RequestRow[]) : []
  }
  return []
}

const dateFormatterTashkent = new Intl.DateTimeFormat('ru-RU', {
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  timeZone: 'Asia/Tashkent',
})
const billingMonthFormatterTashkent = new Intl.DateTimeFormat('ru-RU', {
  month: 'long',
  year: 'numeric',
  timeZone: 'Asia/Tashkent',
})

function formatDateDDMMYYYY(value?: string | null): string {
  if (!value) return '-'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return '-'
  return dateFormatterTashkent.format(parsed)
}

function formatBillingMonthYear(value?: string | null): string {
  if (!value) return '-'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return '-'
  return billingMonthFormatterTashkent.format(parsed)
}

function canResendByStatus(status?: string | null): boolean {
  const raw = String(status || '').trim()
  if (raw.toUpperCase() === 'APPROVED') return true
  const numeric = Number(raw)
  return Number.isFinite(numeric) && numeric >= 1 && numeric <= 5
}

export function RequestsPage() {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(true)
  const [rows, setRows] = useState<RequestRow[]>([])
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [status, setStatus] = useState<string | undefined>(undefined)
  const [urgency, setUrgency] = useState<string | undefined>(undefined)
  const [paymentType, setPaymentType] = useState<string | undefined>(undefined)
  const [currency, setCurrency] = useState<string | undefined>(undefined)
  const [category, setCategory] = useState<string | undefined>(undefined)
  const [vendor, setVendor] = useState<string | undefined>(undefined)
  const [requester, setRequester] = useState<string | undefined>(undefined)
  const [amountMin, setAmountMin] = useState<number | null>(null)
  const [amountMax, setAmountMax] = useState<number | null>(null)
  const [submittedRange, setSubmittedRange] = useState<[Dayjs | null, Dayjs | null] | null>(null)
  const [billingRange, setBillingRange] = useState<[Dayjs | null, Dayjs | null] | null>(null)
  const [sort, setSort] = useState<SortState>({ field: null, order: null })
  const [currentPage, setCurrentPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [selectedRow, setSelectedRow] = useState<RequestRow | null>(null)
  const [selectedDetail, setSelectedDetail] = useState<RequestDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailError, setDetailError] = useState<string | null>(null)
  const [openNoteModal, setOpenNoteModal] = useState(false)
  const [resendLoading, setResendLoading] = useState(false)
  const [isTenantAdmin, setIsTenantAdmin] = useState(false)
  const [editOpen, setEditOpen] = useState(false)
  const [editSaving, setEditSaving] = useState(false)
  const [editDraft, setEditDraft] = useState<RequestModalEditDraft | null>(null)
  const [vendorSearchApi, setVendorSearchApi] = useState('')
  const [debouncedVendorSearchApi, setDebouncedVendorSearchApi] = useState('')
  const [amortizedOnly, setAmortizedOnly] = useState(false)
  const { value: storedPrefs, setValue: setStoredPrefs, isLoading: prefsLoading } = useUserPreference<RequestsPagePreferences>({
    key: REQUESTS_FILTER_PREF_KEY,
    defaultValue: defaultRequestsPreferences,
    normalize: (raw, fallback) => ({ ...fallback, ...(raw as Partial<RequestsPagePreferences>) }),
    debounceMs: 300,
  })
  const hydratedFromPrefsRef = useRef(false)

  useEffect(() => {
    if (prefsLoading || hydratedFromPrefsRef.current) return
    hydratedFromPrefsRef.current = true
    setSearch(storedPrefs.search || '')
    setStatus(storedPrefs.status)
    setUrgency(storedPrefs.urgency)
    setPaymentType(storedPrefs.paymentType)
    setCurrency(storedPrefs.currency)
    setCategory(storedPrefs.category)
    setVendor(storedPrefs.vendor)
    setRequester(storedPrefs.requester)
    setAmountMin(storedPrefs.amountMin ?? null)
    setAmountMax(storedPrefs.amountMax ?? null)
    setSubmittedRange(parseStoredRange(storedPrefs.submittedRange))
    setBillingRange(parseStoredRange(storedPrefs.billingRange))
    setAmortizedOnly(Boolean(storedPrefs.amortizedOnly))
  }, [storedPrefs, prefsLoading])

  useEffect(() => {
    setStoredPrefs({
      search,
      status,
      urgency,
      paymentType,
      currency,
      category,
      vendor,
      requester,
      amountMin,
      amountMax,
      submittedRange: serializeRange(submittedRange),
      billingRange: serializeRange(billingRange),
      amortizedOnly,
    })
  }, [
    search,
    status,
    urgency,
    paymentType,
    currency,
    category,
    vendor,
    requester,
    amountMin,
    amountMax,
    submittedRange,
    billingRange,
    amortizedOnly,
    setStoredPrefs,
  ])

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const opts = await getRequestFormOptions()
        if (!cancelled) {
          setIsTenantAdmin(Boolean(opts.is_tenant_admin))
        }
      } catch {
        if (!cancelled) {
          setIsTenantAdmin(false)
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    const id = window.setTimeout(() => setDebouncedSearch(search), 250)
    return () => window.clearTimeout(id)
  }, [search])

  useEffect(() => {
    const id = window.setTimeout(() => setDebouncedVendorSearchApi(vendorSearchApi.trim()), 300)
    return () => window.clearTimeout(id)
  }, [vendorSearchApi])

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setError(null)
      setLoading(true)
      try {
        const params = new URLSearchParams()
        const submittedFrom = submittedRange?.[0]?.format('YYYY-MM-DD')
        const submittedTo = submittedRange?.[1]?.format('YYYY-MM-DD')
        const billingFrom = billingRange?.[0]?.format('YYYY-MM-DD')
        const billingTo = billingRange?.[1]?.format('YYYY-MM-DD')
        if (submittedFrom) params.set('submitted_from', submittedFrom)
        if (submittedTo) params.set('submitted_to', submittedTo)
        if (billingFrom) params.set('billing_from', billingFrom)
        if (billingTo) params.set('billing_to', billingTo)
        if (debouncedVendorSearchApi) params.set('vendor_search', debouncedVendorSearchApi)
        if (amortizedOnly) params.set('amortized_only', '1')
        const query = params.toString()
        const endpoint = query ? `/api/requests/?${query}` : '/api/requests/'

        const res = await apiFetch(endpoint)
        const json = await res.json().catch(() => null)
        if (!res.ok) {
          throw new Error(typeof json === 'object' && json ? JSON.stringify(json) : `HTTP ${res.status}`)
        }
        if (!cancelled) {
          const normalized = normalizeRows(json)
          setRows(normalized)
        }
      } catch (e: any) {
        if (!cancelled) {
          setRows([])
          setError(e?.message || 'Ошибка запроса')
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [submittedRange, billingRange, debouncedVendorSearchApi, amortizedOnly])

  const optionize = (values: string[]) =>
    [...new Set(values.filter(Boolean))].sort((a, b) => a.localeCompare(b)).map((value) => ({
      label: value,
      value,
    }))

  const requesterOptions = useMemo(() => {
    const map = new Map<string, string>()
    for (const row of rows) {
      const key = row.requester !== null ? String(row.requester) : ''
      if (!key) continue
      map.set(key, row.requester_username || `User #${key}`)
    }
    return [...map.entries()].map(([value, label]) => ({ value, label }))
  }, [rows])

  const filteredRows = useMemo(() => {
    const normalizedSearch = debouncedSearch.trim().toLowerCase()
    let data = rows.filter((row) => {
      if (status && row.status !== status) return false
      if (urgency && row.urgency !== urgency) return false
      if (paymentType && row.payment_type !== paymentType) return false
      if (currency && row.currency !== currency) return false
      if (category && row.category !== category) return false
      if (vendor && row.vendor !== vendor) return false
      if (requester && String(row.requester) !== requester) return false
      if (amountMin !== null && Number(row.amount) < amountMin) return false
      if (amountMax !== null && Number(row.amount) > amountMax) return false
      if (!normalizedSearch) return true
      const haystack = JSON.stringify(row).toLowerCase()
      return haystack.includes(normalizedSearch)
    })

    if (sort.field && sort.order) {
      const dir = sort.order === 'ascend' ? 1 : -1
      data = [...data].sort((a, b) => {
        const av = a[sort.field as keyof RequestRow]
        const bv = b[sort.field as keyof RequestRow]
        if (av === bv) return 0
        if (av === null || av === undefined) return -1 * dir
        if (bv === null || bv === undefined) return 1 * dir
        if (sort.field === 'amount') {
          const an = Number(av)
          const bn = Number(bv)
          if (!Number.isNaN(an) && !Number.isNaN(bn)) return (an - bn) * dir
        }
        if (typeof av === 'number' && typeof bv === 'number') return (av - bv) * dir
        return String(av).localeCompare(String(bv)) * dir
      })
    }
    return data
  }, [rows, debouncedSearch, status, urgency, paymentType, currency, category, vendor, requester, amountMin, amountMax, sort])

  useEffect(() => {
    setCurrentPage(1)
  }, [debouncedSearch, status, urgency, paymentType, currency, category, vendor, requester, amountMin, amountMax, submittedRange, billingRange, debouncedVendorSearchApi, amortizedOnly])

  const getStatusColor = (value: string): string | undefined => {
    const normalized = String(value || '').trim().toUpperCase()
    if (normalized === 'REJECTED') return 'error'
    if (normalized === 'APPROVED') return 'success'
    if (normalized === 'PAYED') return '#8c8c8c'
    if (normalized === '1-5') return 'warning'
    const numericStatus = Number(normalized)
    if (Number.isFinite(numericStatus) && numericStatus >= 1 && numericStatus <= 5) return 'warning'
    return undefined
  }

  const saveDetailEdit = async () => {
    if (!selectedRow || !selectedDetail || !editDraft) return
    if (!editDraft) return
    if (!editDraft.title.trim()) {
      message.warning('Введите название заявки')
      return
    }
    setEditSaving(true)
    try {
      const payload = {
        title: editDraft.title.trim(),
        description: editDraft.description.trim(),
        amount: editDraft.amount ?? 0,
        currency: editDraft.currency,
        status: editDraft.status,
        urgency: editDraft.urgency,
        payment_type: editDraft.payment_type,
        category: editDraft.category,
        vendor: editDraft.vendor,
        payment_purpose: editDraft.payment_purpose.trim() || undefined,
        requester: editDraft.requester ? Number(editDraft.requester) : null,
        billing_date: editDraft.billing_date ? editDraft.billing_date.startOf('month').format('YYYY-MM-DD') : undefined,
        amortization_months: editDraft.amortization_enabled ? editDraft.amortization_months : 1,
      }
      const res = await apiFetch(`/api/requests/${selectedRow.id}/`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      const json = await res.json().catch(() => null)
      if (!res.ok) {
        throw new Error(typeof json === 'object' && json ? JSON.stringify(json) : `HTTP ${res.status}`)
      }
      const nextDetail: RequestDetail = {
        ...selectedDetail,
        title: payload.title,
        description: payload.description,
        amount: payload.amount,
        currency: payload.currency,
        status: payload.status,
        urgency: payload.urgency,
        payment_type: payload.payment_type,
        category: payload.category,
        vendor: payload.vendor,
        payment_purpose: payload.payment_purpose || '',
        requester: payload.requester,
        billing_date: payload.billing_date || selectedDetail.billing_date,
        amortization_months: payload.amortization_months,
        is_amortized: payload.amortization_months > 1,
      }
      setSelectedDetail(nextDetail)
      setSelectedRow((prev) =>
        prev
          ? {
              ...prev,
              title: payload.title,
              description: payload.description,
              amount: payload.amount,
              currency: payload.currency,
              status: payload.status,
              urgency: payload.urgency,
              payment_type: payload.payment_type,
              category: payload.category,
              vendor: payload.vendor,
              payment_purpose: payload.payment_purpose || '',
              requester: payload.requester,
              billing_date: payload.billing_date || prev.billing_date,
              amortization_months: payload.amortization_months,
              is_amortized: payload.amortization_months > 1,
            }
          : prev,
      )
      setRows((prev) =>
        prev.map((row) =>
          row.id === selectedRow.id
            ? {
                ...row,
                title: payload.title,
                description: payload.description,
                amount: payload.amount,
                currency: payload.currency,
                status: payload.status,
                urgency: payload.urgency,
                payment_type: payload.payment_type,
                category: payload.category,
                vendor: payload.vendor,
                payment_purpose: payload.payment_purpose || '',
                requester: payload.requester,
                billing_date: payload.billing_date || row.billing_date,
                amortization_months: payload.amortization_months,
                is_amortized: payload.amortization_months > 1,
              }
            : row,
        ),
      )
      message.success('Заявка обновлена')
      setEditOpen(false)
    } catch (e: any) {
      message.error(e?.message || 'Не удалось сохранить заявку')
    } finally {
      setEditSaving(false)
    }
  }

  useEffect(() => {
    if (!selectedRow) {
      setSelectedDetail(null)
      setDetailLoading(false)
      setDetailError(null)
      return
    }
    let cancelled = false
    ;(async () => {
      setDetailLoading(true)
      setDetailError(null)
      try {
        const res = await apiFetch(`/api/requests/${selectedRow.id}/`)
        const json = (await res.json().catch(() => null)) as RequestDetail | null
        if (!res.ok) {
          throw new Error(typeof json === 'object' && json ? JSON.stringify(json) : `HTTP ${res.status}`)
        }
        if (!cancelled) setSelectedDetail(json)
      } catch (e: any) {
        if (!cancelled) setDetailError(e?.message || 'Ошибка загрузки заявки')
      } finally {
        if (!cancelled) setDetailLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [selectedRow])

  const columns: ColumnsType<RequestRow> = [
    { title: 'ID', dataIndex: 'id', width: 64, sorter: true },
    { title: 'Название', dataIndex: 'title', width: 180, sorter: true },
    {
      title: 'Описание заявки',
      dataIndex: 'description',
      width: 280,
      render: (value: string | undefined) => value || '—',
    },
    { title: 'Категория', dataIndex: 'category', sorter: true },
    { title: 'Поставщик', dataIndex: 'vendor', sorter: true },
    {
      title: 'Сумма',
      dataIndex: 'amount',
      sorter: true,
      render: (_, row) => `${Number(row.amount).toLocaleString('ru-RU')} ${row.currency}`,
    },
    {
      title: 'Статус',
      dataIndex: 'status',
      sorter: true,
      render: (value: string) => <Tag color={getStatusColor(value)}>{value}</Tag>,
    },
    { title: 'Тип оплаты', dataIndex: 'payment_type', sorter: true },
    {
      title: 'Заявитель',
      key: 'requester_label',
      sorter: true,
      render: (_, row) => row.requester_username || (row.requester ? `User #${row.requester}` : '-'),
    },
    {
      title: 'Отправлено',
      dataIndex: 'submitted_at',
      sorter: true,
      render: (value: string) => formatDateDDMMYYYY(value),
    },
    {
      title: 'Дата биллинга',
      dataIndex: 'billing_date',
      sorter: true,
      render: (value: string) => formatBillingMonthYear(value),
    },
    {
      title: 'Амортизация',
      key: 'is_amortized',
      render: (_, row) => (row.is_amortized ? <Tag color="processing">{`${row.amortization_months || 0} мес.`}</Tag> : '—'),
    },
    {
      title: 'Действия',
      key: 'actions',
      width: 120,
      render: (_, row) => (
        <Button
          size="small"
          icon={<CopyOutlined />}
          onClick={(e) => {
            e.stopPropagation()
            void duplicateRequest(row.id)
          }}
        >
          Копировать
        </Button>
      ),
    },
  ]

  const onTableChange: TableProps<RequestRow>['onChange'] = (_, __, sorter) => {
    if (_?.current) setCurrentPage(_.current)
    if (_?.pageSize) setPageSize(_.pageSize)
    const normalized = Array.isArray(sorter) ? sorter[0] : sorter
    if (!normalized?.field || !normalized.order) {
      setSort({ field: null, order: null })
      return
    }
    setSort({
      field: normalized.field as keyof RequestRow,
      order: normalized.order,
    })
  }

  const activeDetail = selectedDetail

  const resendRequest = async (requestId: number) => {
    setResendLoading(true)
    try {
      const { resent, pendingCurrentStep } = await resendRequestApprovals(requestId)
      if (resent > 0) {
        message.success(`Заявки отправлены повторно: ${resent}`)
      } else if (pendingCurrentStep > 0) {
        message.warning(
          `На текущем этапе есть pending-согласования (${pendingCurrentStep}), но отправка не удалась. Проверьте bridge URL/token.`,
        )
      } else {
        message.info('Нет pending-согласований для повторной отправки')
      }
    } catch (e: any) {
      message.error(e?.message || 'Не удалось отправить запрос повторно')
    } finally {
      setResendLoading(false)
    }
  }

  async function duplicateRequest(requestId: number) {
    try {
      const created = await copyPortalRequest(requestId)
      message.success(`Черновик-копия создан: #${created.request_id}`)
      navigate(`/requests/${created.request_id}`)
    } catch (e: any) {
      message.error(e?.message || 'Не удалось скопировать заявку')
    }
  }

  const resetFilters = () => {
    setSearch('')
    setVendorSearchApi('')
    setStatus(undefined)
    setUrgency(undefined)
    setPaymentType(undefined)
    setCurrency(undefined)
    setCategory(undefined)
    setVendor(undefined)
    setRequester(undefined)
    setAmountMin(null)
    setAmountMax(null)
    setSubmittedRange(null)
    setBillingRange(null)
    setAmortizedOnly(false)
    setSort({ field: null, order: null })
    setCurrentPage(1)
  }

  return (
    <Card>
      <Space align="center" style={{ justifyContent: 'space-between', width: '100%', flexWrap: 'wrap' }}>
        <Typography.Title level={4} style={{ marginTop: 0 }}>
          Список заявок
        </Typography.Title>
        <Space>
          <Button onClick={() => navigate('/requests/audit')}>Аудит месяцев</Button>
          <Button onClick={() => navigate('/requests/auto-config')}>Автозаявки</Button>
          <Button type="primary" icon={<FileAddOutlined />} onClick={() => navigate('/requests/new')}>
            Новая заявка
          </Button>
        </Space>
      </Space>
      <Space direction="vertical" size={12} style={{ display: 'flex', marginTop: 12, marginBottom: 12 }}>
        <Space wrap>
          <Input
            placeholder="Поиск: категория, поставщик, назначение, описание"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            allowClear
            style={{ minWidth: 320 }}
          />
          <Select
            placeholder="Статус"
            allowClear
            style={{ width: 180 }}
            value={status}
            onChange={(value) => setStatus(value)}
            options={optionize(rows.map((r) => r.status))}
          />
          <Select
            placeholder="Тип оплаты"
            allowClear
            style={{ width: 200 }}
            value={paymentType}
            onChange={(value) => setPaymentType(value)}
            options={optionize(rows.map((r) => r.payment_type))}
          />
          <Button onClick={resetFilters}>Сбросить фильтры</Button>
        </Space>
        <Collapse
          size="small"
          items={[
            {
              key: 'advanced',
              label: 'Расширенные фильтры',
              children: (
                <Space direction="vertical" size={12} style={{ display: 'flex' }}>
                  <Input
                    placeholder="Поставщик: поиск на сервере (название)"
                    value={vendorSearchApi}
                    onChange={(e) => setVendorSearchApi(e.target.value)}
                    allowClear
                    style={{ maxWidth: 360 }}
                  />
                  <Space wrap size={[12, 12]}>
                    <Space align="center">
                      <Typography.Text style={{ marginBottom: 0 }}>Только с амортизацией</Typography.Text>
                      <Switch checked={amortizedOnly} onChange={setAmortizedOnly} />
                    </Space>
                    <Select
                      placeholder="Срочность"
                      allowClear
                      style={{ width: 180 }}
                      value={urgency}
                      onChange={(value) => setUrgency(value)}
                      options={optionize(rows.map((r) => r.urgency))}
                    />
                    <Select
                      placeholder="Валюта"
                      allowClear
                      style={{ width: 140 }}
                      value={currency}
                      onChange={(value) => setCurrency(value)}
                      options={optionize(rows.map((r) => r.currency))}
                    />
                    <Select
                      placeholder="Категория"
                      allowClear
                      style={{ width: 220 }}
                      value={category}
                      onChange={(value) => setCategory(value)}
                      options={optionize(rows.map((r) => r.category))}
                    />
                    <Select
                      placeholder="Поставщик"
                      allowClear
                      style={{ width: 220 }}
                      value={vendor}
                      onChange={(value) => setVendor(value)}
                      options={optionize(rows.map((r) => r.vendor))}
                    />
                    <Select
                      placeholder="Заявитель"
                      allowClear
                      style={{ width: 200 }}
                      value={requester}
                      onChange={(value) => setRequester(value)}
                      options={requesterOptions}
                    />
                  </Space>
                  <Space wrap>
                    <DatePicker.RangePicker
                      value={submittedRange}
                      onChange={(value) => setSubmittedRange(value)}
                      placeholder={['submitted_from', 'submitted_to']}
                    />
                    <DatePicker.RangePicker
                      value={billingRange}
                      onChange={(value) => setBillingRange(value)}
                      placeholder={['billing_from', 'billing_to']}
                    />
                    <InputNumber
                      placeholder="Мин. сумма"
                      value={amountMin}
                      onChange={(value) => setAmountMin(value)}
                      min={0}
                    />
                    <InputNumber
                      placeholder="Макс. сумма"
                      value={amountMax}
                      onChange={(value) => setAmountMax(value)}
                      min={0}
                    />
                  </Space>
                </Space>
              ),
            },
          ]}
        />
      </Space>
      {loading ? <Skeleton active style={{ marginTop: 16 }} /> : null}
      {error ? <Alert type="error" showIcon message={error} style={{ marginTop: 16 }} /> : null}
      {!loading && !error ? (
        <Table<RequestRow>
          rowKey="id"
          size="small"
          columns={columns}
          dataSource={filteredRows}
          onChange={onTableChange}
          onRow={(record) => ({
            onClick: () => setSelectedRow(record),
            className: isPayedMissingLinkedExpense(record) ? 'requests-row--payed-no-expense' : undefined,
            style: { cursor: 'pointer' },
          })}
          pagination={{
            current: currentPage,
            pageSize,
            showSizeChanger: true,
            pageSizeOptions: [20, 50, 100, 200],
          }}
          scroll={{ x: 1200 }}
        />
      ) : null}
      <RequestDetailModal
        open={Boolean(selectedRow)}
        onCancel={() => setSelectedRow(null)}
        detail={activeDetail}
        loading={detailLoading}
        error={detailError}
        actions={
          selectedRow ? (
            <Space>
              <Button icon={<FileSearchOutlined />} onClick={() => navigate(`/requests/${selectedRow.id}`)}>
                Открыть страницу
              </Button>
              <Button icon={<MessageOutlined />} onClick={() => setOpenNoteModal(true)}>
                Добавить заметку
              </Button>
              <Button icon={<CopyOutlined />} onClick={() => selectedRow && void duplicateRequest(selectedRow.id)}>
                Копировать
              </Button>
              {isTenantAdmin ? (
                <Button
                  onClick={() => {
                    if (!selectedDetail) return
                    setEditDraft({
                      title: selectedDetail.title || '',
                      description: selectedDetail.description || '',
                      amount: Number.isFinite(Number(selectedDetail.amount)) ? Number(selectedDetail.amount) : null,
                      currency: selectedDetail.currency || 'UZS',
                      status: selectedDetail.status || '',
                      urgency: selectedDetail.urgency || '',
                      payment_type: selectedDetail.payment_type || '',
                      category: selectedDetail.category || '',
                      vendor: selectedDetail.vendor || '',
                      payment_purpose: selectedDetail.payment_purpose || '',
                      billing_date: selectedDetail.billing_date ? dayjs(selectedDetail.billing_date) : null,
                      requester: selectedDetail.requester != null ? String(selectedDetail.requester) : '',
                      amortization_enabled: Number(selectedDetail.amortization_months || 1) > 1,
                      amortization_months:
                        Number(selectedDetail.amortization_months || 1) > 1
                          ? Number(selectedDetail.amortization_months || 2)
                          : 2,
                    })
                    setEditOpen(true)
                  }}
                >
                  Редактировать
                </Button>
              ) : null}
              <Button
                type="primary"
                icon={<ReloadOutlined />}
                loading={resendLoading}
                disabled={!canResendByStatus(selectedRow.status)}
                title={
                  canResendByStatus(selectedRow.status)
                    ? 'Повторно отправить pending-согласования текущего этапа'
                    : 'Доступно для этапов согласования (1–5) и для заявок со статусом APPROVED'
                }
                onClick={() => resendRequest(selectedRow.id)}
              >
                Отправить запрос(ы) повторно
              </Button>
            </Space>
          ) : null
        }
      />
      <NoteCreateModal
        open={openNoteModal}
        onCancel={() => setOpenNoteModal(false)}
        targetType="request"
        targetId={selectedRow?.id || null}
      />
      <Modal
        open={editOpen}
        title={selectedRow ? `Редактировать заявку #${selectedRow.id}` : 'Редактировать заявку'}
        onCancel={() => setEditOpen(false)}
        footer={null}
        destroyOnClose
      >
        <Space direction="vertical" size={12} style={{ display: 'flex' }}>
          <Input
            placeholder="Название"
            value={editDraft?.title || ''}
            onChange={(e) => setEditDraft((prev) => (prev ? { ...prev, title: e.target.value } : prev))}
          />
          <Input.TextArea
            rows={4}
            placeholder="Описание"
            value={editDraft?.description || ''}
            onChange={(e) => setEditDraft((prev) => (prev ? { ...prev, description: e.target.value } : prev))}
          />
          <Space wrap>
            <InputNumber
              min={0}
              placeholder="Сумма"
              value={editDraft?.amount ?? undefined}
              onChange={(value) => setEditDraft((prev) => (prev ? { ...prev, amount: typeof value === 'number' ? value : null } : prev))}
            />
            <Select
              style={{ width: 120 }}
              placeholder="Валюта"
              value={editDraft?.currency}
              onChange={(value) => setEditDraft((prev) => (prev ? { ...prev, currency: value } : prev))}
              options={optionize(rows.map((r) => r.currency))}
            />
            <Select
              style={{ width: 160 }}
              placeholder="Статус"
              value={editDraft?.status}
              onChange={(value) => setEditDraft((prev) => (prev ? { ...prev, status: value } : prev))}
              options={optionize(rows.map((r) => r.status))}
              showSearch
            />
            <Select
              style={{ width: 180 }}
              placeholder="Срочность"
              value={editDraft?.urgency}
              onChange={(value) => setEditDraft((prev) => (prev ? { ...prev, urgency: value } : prev))}
              options={optionize(rows.map((r) => r.urgency))}
              showSearch
            />
          </Space>
          <Space wrap>
            <Select
              style={{ minWidth: 220 }}
              placeholder="Тип оплаты"
              value={editDraft?.payment_type}
              onChange={(value) => setEditDraft((prev) => (prev ? { ...prev, payment_type: value } : prev))}
              options={optionize(rows.map((r) => r.payment_type))}
              showSearch
            />
            <Select
              style={{ minWidth: 220 }}
              placeholder="Категория"
              value={editDraft?.category}
              onChange={(value) => setEditDraft((prev) => (prev ? { ...prev, category: value } : prev))}
              options={optionize(rows.map((r) => r.category))}
              showSearch
            />
            <Select
              style={{ minWidth: 220 }}
              placeholder="Поставщик"
              value={editDraft?.vendor}
              onChange={(value) => setEditDraft((prev) => (prev ? { ...prev, vendor: value } : prev))}
              options={optionize(rows.map((r) => r.vendor))}
              showSearch
            />
          </Space>
          <Input
            placeholder="Назначение платежа"
            value={editDraft?.payment_purpose || ''}
            onChange={(e) => setEditDraft((prev) => (prev ? { ...prev, payment_purpose: e.target.value } : prev))}
          />
          <Space wrap>
            <DatePicker
              picker="month"
              format="MM.YYYY"
              value={editDraft?.billing_date ?? null}
              onChange={(value) => setEditDraft((prev) => (prev ? { ...prev, billing_date: value } : prev))}
              inputReadOnly
            />
            <Select
              style={{ minWidth: 220 }}
              placeholder="Заявитель"
              value={editDraft?.requester || undefined}
              onChange={(value) => setEditDraft((prev) => (prev ? { ...prev, requester: value } : prev))}
              options={requesterOptions}
              allowClear
              showSearch
            />
          </Space>
          <Space wrap align="center">
            <Typography.Text style={{ marginBottom: 0 }}>Амортизировать расход</Typography.Text>
            <Switch
              checked={Boolean(editDraft?.amortization_enabled)}
              onChange={(checked) =>
                setEditDraft((prev) =>
                  prev
                    ? {
                        ...prev,
                        amortization_enabled: checked,
                        amortization_months: checked ? prev.amortization_months : 2,
                      }
                    : prev,
                )
              }
            />
            {editDraft?.amortization_enabled ? (
              <Select
                style={{ width: 180 }}
                value={editDraft.amortization_months}
                onChange={(value) =>
                  setEditDraft((prev) => (prev ? { ...prev, amortization_months: value } : prev))
                }
                options={[2, 3, 4, 5, 6].map((m) => ({ value: m, label: `${m}` }))}
              />
            ) : null}
          </Space>
          <Button type="primary" loading={editSaving} onClick={() => void saveDetailEdit()}>
            Сохранить
          </Button>
        </Space>
      </Modal>
    </Card>
  )
}

