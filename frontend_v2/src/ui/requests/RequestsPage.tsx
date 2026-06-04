import { useEffect, useMemo, useRef, useState } from 'react'
import { Alert, Button, Card, Collapse, DatePicker, Input, InputNumber, Modal, Select, Skeleton, Space, Switch, Table, Tag, Typography, message } from 'antd'
import type { ColumnsType, TableProps } from 'antd/es/table'
import type { Dayjs } from 'dayjs'
import dayjs from 'dayjs'
import { useNavigate } from 'react-router-dom'
import { CopyOutlined, FileAddOutlined, FileSearchOutlined, MessageOutlined, SendOutlined } from '@ant-design/icons'
import {
  apiFetch,
  copyPortalRequest,
  getRequestFormOptions,
  getRequestCategories,
  getRequestVendors,
  parseErrorBody,
  submitRequestForApproval,
  type RequestCategoryOption,
  type RequestFormOptionsPaymentType,
  type RequestFormOptionsRequester,
} from '../../lib/api'
import { notifyApiSuccess } from '../../lib/apiNotify'
import { isPayedMissingLinkedExpense, type RequestExpenseLink } from '../../lib/requestExpense'
import { formatRequestBillingMonth, formatRequestDate, getRequestStatusColor } from '../../lib/requestUtils'
import { requestReturnToForDetail } from '../../lib/requestNavigation'
import { RequestDetailModal, type RequestDetail } from './RequestDetailModal'
import { labelBlockAboveField } from '../formSpacing'
import { RequestAiChatButton } from './RequestAiChatButton'
import { NoteCreateModal } from '../NoteCreateModal'
import { useInfiniteList, useRestoreInfinitePages } from '../../lib/useInfiniteList'
import { useListPageSession } from '../../lib/useListPageSession'
import { useUserPreference } from '../../lib/useUserPreference'
import { ListInfiniteScrollFooter } from '../ListInfiniteScrollFooter'

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
  expense_id: string
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
  payedMissingExpense: boolean
}

const REQUESTS_FILTER_PREF_KEY = 'requests.page.filters.v1'
const REQUESTS_LIST_SESSION_KEY = 'list-session:/requests'

const STATUS_OPTIONS = ['DRAFT', '1', '2', '3', '4', '5', 'APPROVED', 'PAYED', 'REJECTED'].map((v) => ({ label: v, value: v }))
const PAYMENT_TYPE_OPTIONS = ['Наличные', 'Перечисление', 'Пополнение', 'Платежная карта', 'Начисление ЗП'].map((v) => ({ label: v, value: v }))
const URGENCY_OPTIONS = ['Низко', 'Обычно', 'Срочно'].map((v) => ({ label: v, value: v }))
const CURRENCY_OPTIONS = ['UZS', 'USD', 'EUR', 'RUB'].map((v) => ({ label: v, value: v }))

type RequestsListSession = {
  scrollY: number
  pagesLoaded?: number
  selectedRowId?: number | null
  sort?: SortState
}
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
  payedMissingExpense: false,
}

function orderingFromSort(sort: SortState): string | undefined {
  if (!sort.field || !sort.order) return undefined
  if (sort.field === 'id') return sort.order === 'descend' ? '-id' : 'id'
  const prefix = sort.order === 'descend' ? '-' : ''
  const tiebreaker = sort.order === 'descend' ? ',-id' : ',id'
  return `${prefix}${sort.field}${tiebreaker}`
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

export function RequestsPage() {
  const navigate = useNavigate()
  const [restorePages, setRestorePages] = useState<number | undefined>(undefined)
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
  const [categoryOptions, setCategoryOptions] = useState<RequestCategoryOption[]>([])
  const [vendorOptions, setVendorOptions] = useState<string[]>([])
  const [selectedRow, setSelectedRow] = useState<RequestRow | null>(null)
  const pendingSelectedRowIdRef = useRef<number | null>(null)
  const [selectedDetail, setSelectedDetail] = useState<RequestDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailError, setDetailError] = useState<string | null>(null)
  const [openNoteModal, setOpenNoteModal] = useState(false)
  const [submitLoading, setSubmitLoading] = useState(false)
  const [isTenantAdmin, setIsTenantAdmin] = useState(false)
  const [editOpen, setEditOpen] = useState(false)
  const [editSaving, setEditSaving] = useState(false)
  const [editDraft, setEditDraft] = useState<RequestModalEditDraft | null>(null)
  const [requestFormPaymentTypes, setRequestFormPaymentTypes] = useState<RequestFormOptionsPaymentType[]>([])
  const [requesterCandidates, setRequesterCandidates] = useState<RequestFormOptionsRequester[]>([])
  const [vendorSearchApi, setVendorSearchApi] = useState('')
  const [debouncedVendorSearchApi, setDebouncedVendorSearchApi] = useState('')
  const [amortizedOnly, setAmortizedOnly] = useState(false)
  const [payedMissingExpense, setPayedMissingExpense] = useState(false)
  const { value: storedPrefs, setValue: setStoredPrefs, isLoading: prefsLoading } = useUserPreference<RequestsPagePreferences>({
    key: REQUESTS_FILTER_PREF_KEY,
    defaultValue: defaultRequestsPreferences,
    normalize: (raw, fallback) => ({ ...fallback, ...(raw as Partial<RequestsPagePreferences>) }),
    debounceMs: 300,
  })
  const hydratedFromPrefsRef = useRef(false)
  const [prefsHydrated, setPrefsHydrated] = useState(false)

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
    setPayedMissingExpense(Boolean(storedPrefs.payedMissingExpense))
    setPrefsHydrated(true)
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
      payedMissingExpense,
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
    payedMissingExpense,
    setStoredPrefs,
  ])

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const opts = await getRequestFormOptions()
        if (!cancelled) {
          setIsTenantAdmin(Boolean(opts.is_tenant_admin))
          setRequestFormPaymentTypes(opts.payment_types ?? [])
          setRequesterCandidates(opts.requester_candidates ?? [])
        }
      } catch {
        if (!cancelled) {
          setIsTenantAdmin(false)
          setRequestFormPaymentTypes([])
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    Promise.all([getRequestCategories(), getRequestVendors()]).then(([cats, vendors]) => {
      if (!cancelled) {
        setCategoryOptions(cats)
        setVendorOptions(vendors)
      }
    })
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    const id = window.setTimeout(() => setDebouncedSearch(search), 250)
    return () => window.clearTimeout(id)
  }, [search])

  useEffect(() => {
    const id = window.setTimeout(() => setDebouncedVendorSearchApi(vendorSearchApi.trim()), 300)
    return () => window.clearTimeout(id)
  }, [vendorSearchApi])

  const listUrl = useMemo(() => {
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
    if (payedMissingExpense) params.set('payed_missing_expense', '1')
    if (status) params.set('status', status)
    if (urgency) params.set('urgency', urgency)
    if (paymentType) params.set('payment_type', paymentType)
    if (currency) params.set('currency', currency)
    if (category) params.set('category', category)
    if (vendor) params.set('vendor', vendor)
    if (requester) params.set('requester', requester)
    if (amountMin !== null) params.set('amount_min', String(amountMin))
    if (amountMax !== null) params.set('amount_max', String(amountMax))
    if (debouncedSearch.trim()) params.set('search', debouncedSearch.trim())
    const ordering = orderingFromSort(sort)
    if (ordering) params.set('ordering', ordering)
    const query = params.toString()
    return query ? `/api/requests/?${query}` : '/api/requests/'
  }, [
    submittedRange,
    billingRange,
    debouncedVendorSearchApi,
    amortizedOnly,
    payedMissingExpense,
    status,
    urgency,
    paymentType,
    currency,
    category,
    vendor,
    requester,
    amountMin,
    amountMax,
    debouncedSearch,
    sort,
  ])

  const {
    items: rows,
    setItems: setRows,
    loading,
    loadingMore,
    error,
    hasMore: hasMoreRows,
    loadMore,
    sentinelRef,
    pagesLoaded,
  } = useInfiniteList<RequestRow>({ url: listUrl, enabled: !prefsLoading && prefsHydrated })

  useRestoreInfinitePages({
    targetPages: restorePages,
    hasMore: hasMoreRows,
    loading,
    loadMore,
  })

  const optionize = (values: string[]) =>
    [...new Set(values.filter(Boolean))].sort((a, b) => a.localeCompare(b)).map((value) => ({
      label: value,
      value,
    }))

  const editModalPaymentTypeOptions = useMemo(() => {
    const uniq = new Set<string>()
    for (const p of requestFormPaymentTypes) {
      if (p.payment_type) uniq.add(p.payment_type)
    }
    for (const r of rows) {
      if (r.payment_type) uniq.add(r.payment_type)
    }
    return [...uniq].sort((a, b) => a.localeCompare(b)).map((value) => ({ label: value, value }))
  }, [requestFormPaymentTypes, rows])

  const editPaymentTypeFormConfig = useMemo(
    () => requestFormPaymentTypes.find((p) => p.payment_type === editDraft?.payment_type) ?? null,
    [requestFormPaymentTypes, editDraft?.payment_type],
  )

  const editPurposeSelectOptions = useMemo(() => {
    if (!editPaymentTypeFormConfig?.payment_purposes?.length) return []
    return editPaymentTypeFormConfig.payment_purposes.map((p) => ({
      value: p.name,
      label: `${p.name} → ${p.category}`,
    }))
  }, [editPaymentTypeFormConfig])

  const requesterOptions = useMemo(() => {
    if (requesterCandidates.length > 0) {
      return requesterCandidates.map((c) => ({ value: String(c.id), label: c.username }))
    }
    // Fallback: build from loaded rows (e.g. requester-only users see only their own requests)
    const map = new Map<string, string>()
    for (const row of rows) {
      const key = row.requester !== null ? String(row.requester) : ''
      if (!key) continue
      map.set(key, row.requester_username || `User #${key}`)
    }
    return [...map.entries()].map(([value, label]) => ({ value, label }))
  }, [requesterCandidates, rows])

  const { persist: persistListSession } = useListPageSession<RequestsListSession>({
    storageKey: REQUESTS_LIST_SESSION_KEY,
    ready: !loading && !error,
    onRestore: (saved) => {
      if (typeof saved.pagesLoaded === 'number' && saved.pagesLoaded > 1) {
        setRestorePages(saved.pagesLoaded)
      }
      if (saved.sort) setSort(saved.sort)
      if (saved.selectedRowId != null) pendingSelectedRowIdRef.current = Number(saved.selectedRowId)
    },
    getSnapshot: () => ({
      pagesLoaded,
      selectedRowId: selectedRow?.id ?? null,
      sort,
    }),
  })

  useEffect(() => {
    const pendingId = pendingSelectedRowIdRef.current
    if (!pendingId || rows.length === 0) return
    const row = rows.find((r) => r.id === pendingId)
    if (row) {
      setSelectedRow(row)
      pendingSelectedRowIdRef.current = null
    }
  }, [rows])

  const saveDetailEdit = async () => {
    if (!selectedRow || !selectedDetail || !editDraft) return
    if (!editDraft) return
    if (!editDraft.title.trim()) {
      message.warning('Введите название заявки')
      return
    }
    const ptCfg = requestFormPaymentTypes.find((p) => p.payment_type === editDraft.payment_type)
    const purposesConfigured = Boolean(ptCfg?.payment_purposes?.length)
    if (purposesConfigured && !editDraft.payment_purpose.trim()) {
      message.warning('Выберите назначение платежа')
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
        expense_id: editDraft.expense_id.trim() || null,
        requester: editDraft.requester ? Number(editDraft.requester) : null,
        billing_date: editDraft.billing_date ? editDraft.billing_date.startOf('month').format('YYYY-MM-DD') : undefined,
        amortization_months: editDraft.amortization_enabled ? editDraft.amortization_months : 1,
      }
      const res = await apiFetch(
        `/api/requests/${selectedRow.id}/`,
        {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        },
        { notifyOnError: true },
      )
      if (!res.ok) {
        throw new Error(await parseErrorBody(res))
      }
      const json = await res.json().catch(() => null)
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
        expense_id: payload.expense_id,
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
      notifyApiSuccess('Заявка обновлена')
      setEditOpen(false)
    } catch {
      // HTTP/network errors already show toast via apiFetch (notifyOnError)
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
      render: (value: string) => <Tag color={getRequestStatusColor(value)}>{value}</Tag>,
    },
    { title: 'Тип оплаты', dataIndex: 'payment_type', sorter: true },
    {
      title: 'Заявитель',
      key: 'requester_label',
      render: (_, row) => row.requester_username || (row.requester ? `User #${row.requester}` : '-'),
    },
    {
      title: 'Отправлено',
      dataIndex: 'submitted_at',
      sorter: true,
      render: (value: string) => formatRequestDate(value),
    },
    {
      title: 'Дата биллинга',
      dataIndex: 'billing_date',
      sorter: true,
      render: (value: string) => formatRequestBillingMonth(value),
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

  const submitDraft = async (requestId: number) => {
    setSubmitLoading(true)
    try {
      const { status: newStatus } = await submitRequestForApproval(requestId)
      if (!newStatus || newStatus === 'DRAFT') {
        // Backend returns 200 but keeps DRAFT when no approval steps/approvers are configured
        // for this payment type, so nothing was actually routed.
        message.warning('Заявка осталась черновиком: для этого типа оплаты не настроены согласующие.')
        return
      }
      // Changing selectedRow re-triggers the detail fetch, refreshing the approvals list too.
      setSelectedRow((prev) => (prev ? { ...prev, status: newStatus } : prev))
      setSelectedDetail((prev) => (prev ? { ...prev, status: newStatus } : prev))
      setRows((prev) => prev.map((row) => (row.id === requestId ? { ...row, status: newStatus } : row)))
      message.success('Заявка отправлена на согласование')
    } catch (e: any) {
      message.error(e?.message || 'Не удалось отправить заявку на согласование')
    } finally {
      setSubmitLoading(false)
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
    setPayedMissingExpense(false)
    setSort({ field: null, order: null })
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
          <RequestAiChatButton />
          <Button type="primary" icon={<FileAddOutlined />} onClick={() => navigate('/requests/new')}>
            Новая заявка
          </Button>
        </Space>
      </Space>
      <Space direction="vertical" size={12} style={{ display: 'flex', marginTop: 12, marginBottom: 12 }}>
        <Space wrap>
          <Input
            placeholder="Поиск по всем полям"
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
            options={STATUS_OPTIONS}
          />
          <Select
            placeholder="Тип оплаты"
            allowClear
            style={{ width: 200 }}
            value={paymentType}
            onChange={(value) => setPaymentType(value)}
            options={PAYMENT_TYPE_OPTIONS}
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
                    placeholder="Фильтр по поставщику с сервера — перезагружает список"
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
                    <Space align="center">
                      <Typography.Text style={{ marginBottom: 0 }}>PAYED без расхода</Typography.Text>
                      <Switch checked={payedMissingExpense} onChange={setPayedMissingExpense} />
                    </Space>
                    <Select
                      placeholder="Срочность"
                      allowClear
                      style={{ width: 180 }}
                      value={urgency}
                      onChange={(value) => setUrgency(value)}
                      options={URGENCY_OPTIONS}
                    />
                    <Select
                      placeholder="Валюта"
                      allowClear
                      style={{ width: 140 }}
                      value={currency}
                      onChange={(value) => setCurrency(value)}
                      options={CURRENCY_OPTIONS}
                    />
                    <Select
                      placeholder="Категория"
                      allowClear
                      showSearch
                      filterOption={(input, opt) => (opt?.label as string ?? '').toLowerCase().includes(input.toLowerCase())}
                      style={{ width: 220 }}
                      value={category}
                      onChange={(value) => setCategory(value)}
                      options={categoryOptions.map((c) => ({ label: c.name, value: c.name }))}
                    />
                    <Select
                      placeholder="Поставщик"
                      allowClear
                      showSearch
                      filterOption={(input, opt) => (opt?.label as string ?? '').toLowerCase().includes(input.toLowerCase())}
                      style={{ width: 220 }}
                      value={vendor}
                      onChange={(value) => setVendor(value)}
                      options={vendorOptions.map((v) => ({ label: v, value: v }))}
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
                      placeholder={['Отправлено с', 'Отправлено по']}
                    />
                    <DatePicker.RangePicker
                      value={billingRange}
                      onChange={(value) => setBillingRange(value)}
                      placeholder={['Биллинг с', 'Биллинг по']}
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
        <>
          <Table<RequestRow>
            rowKey="id"
            size="small"
            columns={columns}
            dataSource={rows}
            onChange={onTableChange}
            onRow={(record) => ({
              onClick: () => setSelectedRow(record),
              className: isPayedMissingLinkedExpense(record) ? 'requests-row--payed-no-expense' : undefined,
              style: { cursor: 'pointer' },
            })}
            pagination={false}
            scroll={{ x: 1200 }}
          />
          <ListInfiniteScrollFooter
            sentinelRef={sentinelRef}
            hasMore={hasMoreRows}
            loadingMore={loadingMore}
            visibleCount={rows.length}
          />
        </>
      ) : null}
      <RequestDetailModal
        open={Boolean(selectedRow)}
        onCancel={() => setSelectedRow(null)}
        detail={activeDetail}
        loading={detailLoading}
        error={detailError}
        returnTo={
          selectedRow ? requestReturnToForDetail(selectedRow.id, { fromList: true }) : undefined
        }
        actions={
          selectedRow ? (
            <Space wrap size={[8, 8]} style={{ width: '100%' }}>
              <Button
                icon={<FileSearchOutlined />}
                onClick={() => {
                  persistListSession()
                  navigate(`/requests/${selectedRow.id}`)
                }}
              >
                Открыть страницу
              </Button>
              <Button icon={<MessageOutlined />} onClick={() => setOpenNoteModal(true)}>
                Добавить заметку
              </Button>
              <Button icon={<CopyOutlined />} onClick={() => selectedRow && void duplicateRequest(selectedRow.id)}>
                Копировать
              </Button>
              {selectedRow.status === 'DRAFT' ? (
                <Button
                  type="primary"
                  icon={<SendOutlined />}
                  loading={submitLoading}
                  onClick={() => submitDraft(selectedRow.id)}
                >
                  Отправить на согласование
                </Button>
              ) : null}
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
                      expense_id: (selectedDetail.expense_id || '').trim(),
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
              onChange={(value) =>
                setEditDraft((prev) => {
                  if (!prev) return prev
                  const cfg = requestFormPaymentTypes.find((p) => p.payment_type === value)
                  const purposes = cfg?.payment_purposes ?? []
                  if (purposes.length === 0) {
                    return { ...prev, payment_type: value }
                  }
                  const matched = purposes.find((p) => p.name === prev.payment_purpose)
                  if (matched) {
                    return { ...prev, payment_type: value, category: matched.category }
                  }
                  return { ...prev, payment_type: value, payment_purpose: '', category: '' }
                })
              }
              options={editModalPaymentTypeOptions}
              showSearch
            />
            {editPurposeSelectOptions.length === 0 ? (
              <Select
                style={{ minWidth: 220 }}
                placeholder="Категория"
                value={editDraft?.category}
                onChange={(value) => setEditDraft((prev) => (prev ? { ...prev, category: value } : prev))}
                options={optionize(rows.map((r) => r.category))}
                showSearch
              />
            ) : null}
            <Select
              style={{ minWidth: 220 }}
              placeholder="Поставщик"
              value={editDraft?.vendor}
              onChange={(value) => setEditDraft((prev) => (prev ? { ...prev, vendor: value } : prev))}
              options={optionize(rows.map((r) => r.vendor))}
              showSearch
            />
          </Space>
          {editPurposeSelectOptions.length > 0 ? (
            <div>
              <Typography.Text strong style={labelBlockAboveField}>
                Назначение платежа
              </Typography.Text>
              <Select
                placeholder="Выберите назначение"
                style={{ display: 'block', width: '100%', maxWidth: 560 }}
                value={editDraft?.payment_purpose || undefined}
                onChange={(purposeName) =>
                  setEditDraft((prev) => {
                    if (!prev) return prev
                    const cfg = requestFormPaymentTypes.find((p) => p.payment_type === prev.payment_type)
                    const matched = cfg?.payment_purposes?.find((p) => p.name === purposeName)
                    return {
                      ...prev,
                      payment_purpose: purposeName,
                      category: matched?.category ?? '',
                    }
                  })
                }
                options={editPurposeSelectOptions}
                showSearch
                optionFilterProp="label"
              />
            </div>
          ) : (
            <Input
              placeholder="Назначение платежа"
              value={editDraft?.payment_purpose || ''}
              onChange={(e) => setEditDraft((prev) => (prev ? { ...prev, payment_purpose: e.target.value } : prev))}
            />
          )}
          <div>
            <Typography.Text strong style={labelBlockAboveField}>
              ID расхода (expense_id)
            </Typography.Text>
            <Input
              allowClear
              placeholder="Номер расхода / документа"
              value={editDraft?.expense_id || ''}
              onChange={(e) => setEditDraft((prev) => (prev ? { ...prev, expense_id: e.target.value } : prev))}
            />
          </div>
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

