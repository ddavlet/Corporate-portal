import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { message } from 'antd'
import type { Dayjs } from 'dayjs'
import type { UploadFile } from 'antd/es/upload/interface'
import { useNavigate } from 'react-router-dom'
import {
  ApiError,
  createContract,
  createPortalRequest,
  createVendor,
  getRequestFormOptions,
  listContracts,
  listVendors,
  listVendorsPage,
  REQUEST_ATTACHMENT_MAX_FILES,
  type CreatedPortalRequest,
  type PortalRequestCreateBody,
  type RequestFormOptionsPaymentType,
  type VendorDirectoryRow,
  uploadRequestAttachment,
  validateRequestAttachment,
} from '../../lib/api'
import {
  fundingCurrenciesFromHint,
  lockedCurrencyFromHint,
  vendorKindForPaymentType,
} from '../../lib/requestPaymentTypes'
import { clampToAllowedBillingMonth, isAllowedBillingMonth } from '../../lib/billingMonth'
import { monthStartTashkent } from '../../lib/tashkentTime'
import { generalFormPurposes, isCashRegisterTransferPurpose } from '../../lib/cashRegisterTransfer'

/** Fields of the create form (and of its «Новый поставщик» / «Новый договор» dialogs) that can carry an error. */
export type RequestCreateField =
  | 'paymentType'
  | 'requester'
  | 'amount'
  | 'billingDate'
  | 'paymentPurpose'
  | 'vendor'
  | 'contract'
  | 'attachments'
  | 'newVendorName'
  | 'newVendorInn'
  | 'contractNumber'
  | 'contractDateFrom'
  | 'contractFile'

export type RequestCreateFieldErrors = Partial<Record<RequestCreateField, string>>

export type RequestCreateOption = { label: string; value: number }

type FormIssue = { field: RequestCreateField; text: string; level: 'warning' | 'error' }

export type UseRequestCreateFormOptions = {
  /** Base path of the requests list without the trailing «/», e.g. `/tg/requests`. */
  requestsBasePath: string
  /** Called with the new request's id instead of opening `${requestsBasePath}/{id}`. */
  onCreated?: (id: number) => void
  /** Where to make a cash-register transfer instead: the general form hides that purpose (no target-register field). */
  transferHintText?: string
}

export const CASH_REGISTER_TRANSFER_HINT_PORTAL =
  'Перевод между кассами оформляется в разделе «Касса» («Все операции», «Расходы» или «Доходы») кнопкой «Перевести между кассами».'

/** The phone has only «Касса» with the transfer button, without the «Все операции» / «Расходы» / «Доходы» lists. */
export const CASH_REGISTER_TRANSFER_HINT_MOBILE =
  'Перевод между кассами оформляется в разделе «Касса» кнопкой «Перевести между кассами».'

const vendorOptionLabel = (r: Pick<VendorDirectoryRow, 'kind' | 'name' | 'inn'>) =>
  r.kind === 'transfer' && r.inn ? `${r.name} (ИНН ${r.inn})` : r.name

const contractOptionLabel = (r: { contract_number: string; date_from: string; is_expired?: boolean }) =>
  `${r.contract_number} (${r.date_from})${r.is_expired ? ' — просрочен' : ''}`

/**
 * State and handlers of the request create form, shared by the desktop / Mini App page and the phone wizard.
 * Validation shows the same toasts as before; `fieldErrors` additionally holds the error of each field after the user
 * tried to go on (or to save a dialog), recomputed from the current values, so a fixed field loses its error at once.
 */
export function useRequestCreateForm({
  requestsBasePath,
  onCreated,
  transferHintText = CASH_REGISTER_TRANSFER_HINT_PORTAL,
}: UseRequestCreateFormOptions) {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(true)
  const [optionsError, setOptionsError] = useState<string | null>(null)
  const [optionsAttempt, setOptionsAttempt] = useState(0)
  const [formOptions, setFormOptions] = useState<RequestFormOptionsPaymentType[]>([])
  const [contractsModuleEffective, setContractsModuleEffective] = useState(false)
  const [isTenantAdmin, setIsTenantAdmin] = useState(false)
  const [isTenantDirector, setIsTenantDirector] = useState(false)
  const [step, setStep] = useState(0)

  const requiresRequesterSelection = isTenantAdmin || isTenantDirector
  const detailStep = requiresRequesterSelection ? 2 : 1

  const [paymentType, setPaymentType] = useState<string | null>(null)
  const [requesterId, setRequesterId] = useState<number | null>(null)
  const [vendorRefId, setVendorRefId] = useState<number | null>(null)
  const vendorRefIdRef = useRef<number | null>(null)
  vendorRefIdRef.current = vendorRefId
  const [vendorOptions, setVendorOptions] = useState<RequestCreateOption[]>([])
  const [vendorSearchLoading, setVendorSearchLoading] = useState(false)
  const [contractRefId, setContractRefId] = useState<number | null>(null)
  const [contractOptions, setContractOptions] = useState<RequestCreateOption[]>([])
  const [contractLoading, setContractLoading] = useState(false)
  const [contractLoadError, setContractLoadError] = useState(false)

  const [description, setDescription] = useState('')
  const [amount, setAmount] = useState<number | null>(null)
  const [currency, setCurrency] = useState('UZS')
  const [urgency, setUrgency] = useState('Обычно')
  const [paymentPurpose, setPaymentPurpose] = useState<string | null>(null)
  const [billingDate, setBillingDate] = useState<Dayjs | null>(() => monthStartTashkent())
  const [amortizationEnabled, setAmortizationEnabled] = useState(false)
  const [amortizationMonths, setAmortizationMonths] = useState(2)
  const [attachmentFileList, setAttachmentFileList] = useState<UploadFile[]>([])

  const [submitting, setSubmitting] = useState(false)
  const [newVendorOpen, setNewVendorOpen] = useState(false)
  const [newVendorName, setNewVendorName] = useState('')
  const [newVendorInn, setNewVendorInn] = useState('')
  const [newVendorAccount, setNewVendorAccount] = useState('')
  const [newVendorSaving, setNewVendorSaving] = useState(false)
  const [newContractOpen, setNewContractOpen] = useState(false)
  const [newContractSaving, setNewContractSaving] = useState(false)
  const [ncNumber, setNcNumber] = useState('')
  const [ncDateFrom, setNcDateFrom] = useState('')
  const [ncDateTo, setNcDateTo] = useState('')
  const [ncAmount, setNcAmount] = useState<number | null>(null)
  const [ncCurrency, setNcCurrency] = useState('UZS')
  const [ncTerms, setNcTerms] = useState('')
  const [ncAcc, setNcAcc] = useState('')
  const [ncFileList, setNcFileList] = useState<UploadFile[]>([])

  // Which validations the user has already run: their errors are shown under the fields from then on.
  const [stepAttempted, setStepAttempted] = useState<number | null>(null)
  const [submitAttempted, setSubmitAttempted] = useState(false)
  const [newVendorAttempted, setNewVendorAttempted] = useState(false)
  const [newContractAttempted, setNewContractAttempted] = useState(false)

  const activePt = useMemo(
    () => formOptions.find((p) => p.payment_type === paymentType) || null,
    [formOptions, paymentType],
  )

  /** Инвест-типы: кошелёк списания и валюта фиксируются настройкой инвестиционного режима. */
  const fundingHint = activePt?.funding_hint ?? null
  const lockedCurrency = lockedCurrencyFromHint(fundingHint)
  /** «Инвест. наличные» с несколькими инвест-кассами: валюта — одна из валют этих касс. */
  const fundingCurrencies = fundingCurrenciesFromHint(fundingHint)
  const currencyOptions = (fundingCurrencies ?? ['UZS', 'USD', 'EUR', 'RUB']).map((c) => ({ value: c, label: c }))

  /** Заявители, разрешённые настройками формы для выбранного типа оплаты (не все роли заявителя в тенанте). */
  const allowedRequesters = useMemo(() => activePt?.requesters ?? [], [activePt])

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setLoading(true)
      setOptionsError(null)
      try {
        const opts = await getRequestFormOptions()
        if (!cancelled) {
          setFormOptions(opts.payment_types)
          setContractsModuleEffective(opts.contracts_module_effective ?? false)
          setIsTenantAdmin(opts.is_tenant_admin ?? false)
          setIsTenantDirector(opts.is_tenant_director ?? false)
        }
      } catch (e: unknown) {
        if (!cancelled) setOptionsError(e instanceof Error ? e.message : 'Не удалось загрузить настройки формы')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [optionsAttempt])

  /** Loads form-options again (after an error). */
  const reloadFormOptions = useCallback(() => setOptionsAttempt((n) => n + 1), [])

  /** Directory rows limited to the vendors allowed for the chosen payment type, as options. */
  const toVendorOptions = useCallback(
    (rows: VendorDirectoryRow[]): RequestCreateOption[] => {
      let filtered = rows
      if (activePt?.vendor_ids?.length) {
        const allowed = new Set(activePt.vendor_ids)
        filtered = rows.filter((r) => allowed.has(r.id))
      }
      return filtered.map((r) => ({ value: r.id, label: vendorOptionLabel(r) }))
    },
    [activePt],
  )

  /** Vendors of the chosen payment type's kind matching the search, limited to the vendors allowed for the type. */
  const fetchVendorOptions = useCallback(
    async (search: string): Promise<RequestCreateOption[]> => {
      if (!paymentType) return []
      const kind = vendorKindForPaymentType(paymentType)
      return toVendorOptions(await listVendors({ kind, search }))
    },
    [paymentType, toVendorOptions],
  )

  /** Like fetchVendorOptions, but a single request of at most `pageSize` rows (the phone's search picker). */
  const fetchVendorPage = useCallback(
    async (search: string, pageSize: number): Promise<RequestCreateOption[]> => {
      if (!paymentType) return []
      const kind = vendorKindForPaymentType(paymentType)
      return toVendorOptions(await listVendorsPage({ kind, search, page_size: pageSize }))
    },
    [paymentType, toVendorOptions],
  )

  // Only the answer to the latest search may fill the options.
  const vendorRequestRef = useRef(0)
  const loadVendors = useCallback(
    async (search: string) => {
      if (!paymentType) return
      const request = ++vendorRequestRef.current
      setVendorSearchLoading(true)
      let options: RequestCreateOption[] = []
      try {
        options = await fetchVendorOptions(search)
      } catch {
        options = []
      }
      if (request !== vendorRequestRef.current) return
      setVendorOptions(options)
      setVendorSearchLoading(false)
    },
    [paymentType, fetchVendorOptions],
  )

  useEffect(() => {
    if (step >= detailStep && paymentType) {
      void loadVendors('')
    }
  }, [step, paymentType, loadVendors, detailStep])

  useEffect(() => {
    if (step !== detailStep || !paymentType) return
    const pt = formOptions.find((p) => p.payment_type === paymentType)
    const d = pt?.defaults
    if (d) {
      setDescription(d.description ?? '')
      if (d.amount != null && d.amount !== '') {
        const n = Number(d.amount)
        setAmount(Number.isFinite(n) ? n : null)
      } else {
        setAmount(null)
      }
      setCurrency(d.currency || 'UZS')
      setUrgency(d.urgency || 'Обычно')
      const monthShift = d.billing_days_offset ?? 0
      const target = monthStartTashkent().add(monthShift, 'month')
      setBillingDate(clampToAllowedBillingMonth(target))
      setPaymentPurpose(d.payment_purpose && !isCashRegisterTransferPurpose(d.payment_purpose) ? d.payment_purpose : null)
      setVendorRefId(d.vendor_ref ?? null)
    } else {
      setBillingDate((prev) => clampToAllowedBillingMonth(prev ?? monthStartTashkent()))
    }
  }, [step, paymentType, formOptions, detailStep])

  useEffect(() => {
    if (step !== detailStep || !fundingCurrencies?.length) return
    // Валюта вне инвест-касс режима недопустима — переключаем на основную (первую).
    if (lockedCurrency) setCurrency(lockedCurrency)
    else setCurrency((prev) => (fundingCurrencies.includes(prev) ? prev : fundingCurrencies[0]))
    // fundingCurrencies пересоздаётся каждый рендер — зависимость по строковому ключу.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step, detailStep, lockedCurrency, fundingCurrencies?.join(',')])

  const searchTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const onVendorSearch = (value: string) => {
    window.clearTimeout(searchTimerRef.current)
    searchTimerRef.current = setTimeout(() => void loadVendors(value), 300)
  }
  useEffect(() => () => window.clearTimeout(searchTimerRef.current), [])

  const contractsRequiredForPt = Boolean(contractsModuleEffective && activePt?.contracts_required)

  useEffect(() => {
    if (!contractsRequiredForPt || !vendorRefId) {
      setContractOptions([])
      setContractRefId(null)
      setContractLoadError(false)
      return
    }
    let cancelled = false
    setContractLoading(true)
    setContractLoadError(false)
    listContracts({ vendor: vendorRefId })
      .then((rows) => {
        if (cancelled) return
        setContractOptions(rows.map((r) => ({ value: r.id, label: contractOptionLabel(r) })))
        setContractRefId((prev) => {
          if (rows.length === 1) return rows[0].id
          if (prev != null && rows.some((r) => r.id === prev)) return prev
          return null
        })
      })
      .catch(() => {
        if (!cancelled) {
          setContractOptions([])
          setContractRefId(null)
          setContractLoadError(true)
        }
      })
      .finally(() => {
        if (!cancelled) setContractLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [contractsRequiredForPt, vendorRefId])

  /**
   * The chosen vendor's contracts fetched now (the phone's picker): its own loading and error with a retry, the
   * options of the form refreshed with the answer. A failure is thrown to the caller.
   */
  const fetchContractOptions = useCallback(async (): Promise<RequestCreateOption[]> => {
    if (!vendorRefId) return []
    const vendor = vendorRefId
    const rows = await listContracts({ vendor })
    const options = rows.map((r) => ({ value: r.id, label: contractOptionLabel(r) }))
    if (vendorRefIdRef.current === vendor) {
      setContractOptions(options)
      setContractLoadError(false)
    }
    return options
  }, [vendorRefId])

  const { purposeOptions, transferPurposeHidden } = useMemo(() => {
    const { purposes, transferHidden } = generalFormPurposes(activePt?.payment_purposes)
    return {
      purposeOptions: purposes.map((p) => ({
        value: p.name,
        label: `${p.name} → ${p.category}`,
      })),
      transferPurposeHidden: transferHidden,
    }
  }, [activePt])

  const stepItems = useMemo(() => {
    if (requiresRequesterSelection) {
      return [{ title: 'Тип оплаты' }, { title: 'Заявитель' }, { title: 'Детали' }]
    }
    return [{ title: 'Тип оплаты' }, { title: 'Детали' }]
  }, [requiresRequesterSelection])

  /** What stops the user from leaving `forStep` (in the order the toasts are shown). */
  const stepIssues = (forStep: number): FormIssue[] => {
    if (forStep === 0 && !paymentType) {
      return [{ field: 'paymentType', level: 'warning', text: 'Выберите тип оплаты' }]
    }
    if (forStep === 1 && requiresRequesterSelection) {
      if (!paymentType || !activePt) {
        return [{ field: 'paymentType', level: 'warning', text: 'Выберите тип оплаты' }]
      }
      if (allowedRequesters.length === 0) {
        return [
          {
            field: 'requester',
            level: 'warning',
            text: 'Для выбранного типа оплаты не настроены заявители. Укажите их в Настройки → Заявки — форма создания.',
          },
        ]
      }
      if (requesterId == null) {
        return [{ field: 'requester', level: 'warning', text: 'Выберите заявителя' }]
      }
    }
    return []
  }

  const attachmentFiles = () =>
    attachmentFileList.map((f) => f.originFileObj as File).filter((f): f is File => f != null)

  /** What stops the request from being created (in the order the toasts are shown). */
  const submitIssues = (): FormIssue[] => {
    const issues: FormIssue[] = []
    if (!paymentType) issues.push({ field: 'paymentType', level: 'error', text: 'Выберите тип оплаты' })
    if (requiresRequesterSelection) {
      if ((activePt?.requesters?.length ?? 0) === 0) {
        issues.push({ field: 'requester', level: 'error', text: 'Для выбранного типа оплаты не настроены заявители.' })
      } else if (requesterId == null) {
        issues.push({ field: 'requester', level: 'error', text: 'Выберите заявителя' })
      }
    }
    if (amount == null || amount <= 0) issues.push({ field: 'amount', level: 'warning', text: 'Укажите сумму' })
    if (!billingDate || !isAllowedBillingMonth(billingDate)) {
      issues.push({ field: 'billingDate', level: 'warning', text: 'Выберите допустимый месяц биллинга' })
    }
    if (transferPurposeHidden && purposeOptions.length === 0) {
      issues.push({ field: 'paymentPurpose', level: 'warning', text: transferHintText })
    }
    if (purposeOptions.length > 0 && !paymentPurpose) {
      issues.push({ field: 'paymentPurpose', level: 'warning', text: 'Выберите назначение платежа' })
    }
    if (!vendorRefId) issues.push({ field: 'vendor', level: 'warning', text: 'Выберите поставщика из справочника' })
    if (contractsRequiredForPt && !contractRefId) {
      issues.push({ field: 'contract', level: 'warning', text: 'Выберите договор' })
    }
    const attachments = attachmentFiles()
    if (attachments.length > REQUEST_ATTACHMENT_MAX_FILES) {
      issues.push({
        field: 'attachments',
        level: 'warning',
        text: `Можно прикрепить максимум ${REQUEST_ATTACHMENT_MAX_FILES} файлов`,
      })
    } else {
      for (const file of attachments) {
        const err = validateRequestAttachment(file)
        if (err) {
          issues.push({ field: 'attachments', level: 'warning', text: `${file.name}: ${err}` })
          break
        }
      }
    }
    return issues
  }

  const newVendorIssues = (): FormIssue[] => {
    if (!paymentType) return []
    const issues: FormIssue[] = []
    if (!newVendorName.trim()) issues.push({ field: 'newVendorName', level: 'warning', text: 'Укажите наименование' })
    if (vendorKindForPaymentType(paymentType) === 'transfer' && !newVendorInn.trim()) {
      issues.push({ field: 'newVendorInn', level: 'warning', text: 'ИНН обязателен для перечисления' })
    }
    return issues
  }

  const newContractIssues = (): FormIssue[] => {
    if (!vendorRefId) return []
    const issues: FormIssue[] = []
    if (!ncNumber.trim()) issues.push({ field: 'contractNumber', level: 'warning', text: 'Укажите номер договора' })
    if (!ncDateFrom.trim()) issues.push({ field: 'contractDateFrom', level: 'warning', text: 'Укажите дату начала' })
    if (!ncFileList[0]?.originFileObj) {
      issues.push({ field: 'contractFile', level: 'warning', text: 'Прикрепите файл договора' })
    }
    return issues
  }

  const notify = (issue: FormIssue) => {
    if (issue.level === 'error') message.error(issue.text)
    else message.warning(issue.text)
  }

  const fieldErrors: RequestCreateFieldErrors = {}
  const collect = (issues: FormIssue[]) => {
    for (const issue of issues) {
      if (!fieldErrors[issue.field]) fieldErrors[issue.field] = issue.text
    }
  }
  if (stepAttempted === step) collect(stepIssues(step))
  if (submitAttempted && step === detailStep) collect(submitIssues())
  if (newVendorAttempted && newVendorOpen) collect(newVendorIssues())
  if (newContractAttempted && newContractOpen) collect(newContractIssues())

  // A dialog opened again starts without the errors of its previous attempt.
  useEffect(() => {
    if (newVendorOpen) setNewVendorAttempted(false)
  }, [newVendorOpen])
  useEffect(() => {
    if (newContractOpen) setNewContractAttempted(false)
  }, [newContractOpen])

  const goNext = () => {
    const issues = stepIssues(step)
    setStepAttempted(step)
    if (issues.length > 0) {
      notify(issues[0])
      return
    }
    setStepAttempted(null)
    setStep((s) => Math.min(s + 1, detailStep))
  }

  const goBack = () => setStep((s) => Math.max(s - 1, 0))

  /** Choosing another payment type starts the rest of the form over. */
  const selectPaymentType = (value: string) => {
    setPaymentType(value)
    // The details of another type start without the errors of a refused submit.
    setSubmitAttempted(false)
    setRequesterId(null)
    setVendorRefId(null)
    setContractRefId(null)
    setPaymentPurpose(null)
    setAmortizationEnabled(false)
    setAmortizationMonths(2)
  }

  /** Another vendor: its contracts are loaded again, the contract choice starts over. */
  const selectVendor = (value: number | null) => {
    setVendorRefId(value)
    setContractRefId(null)
  }

  const submit = async () => {
    const issues = submitIssues()
    setSubmitAttempted(true)
    if (issues.length > 0) {
      notify(issues[0])
      return
    }
    // Narrowing only: submitIssues() has checked these.
    if (!paymentType || amount == null || !billingDate) return
    const attachments = attachmentFiles()

    setSubmitting(true)
    try {
      const titleResolved =
        (activePt?.defaults?.title || '').trim() ||
        (paymentPurpose || '').trim() ||
        'Заявка'
      const payload: PortalRequestCreateBody = {
        title: titleResolved,
        description: description.trim(),
        amount,
        currency,
        payment_type: paymentType,
        urgency,
        billing_date: billingDate.startOf('month').format('YYYY-MM-DD'),
        status: 'DRAFT',
        amortization_months: amortizationEnabled ? amortizationMonths : 1,
      }
      if (requiresRequesterSelection && requesterId != null) {
        payload.requester = requesterId
      }
      if (paymentPurpose) payload.payment_purpose = paymentPurpose
      if (vendorRefId) payload.vendor_ref = vendorRefId
      if (contractRefId) payload.contract_ref = contractRefId
      const res: CreatedPortalRequest = await createPortalRequest(payload)
      for (const file of attachments) {
        await uploadRequestAttachment(res.id, file)
      }
      const id = res.id
      if (typeof id === 'number') {
        if (onCreated) onCreated(id)
        else navigate(`${requestsBasePath}/${id}`, { state: { justCreated: true } })
      } else navigate(requestsBasePath)
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : 'Ошибка сохранения')
    } finally {
      setSubmitting(false)
    }
  }

  const saveNewVendor = async () => {
    if (!paymentType) return
    const issues = newVendorIssues()
    setNewVendorAttempted(true)
    if (issues.length > 0) {
      notify(issues[0])
      return
    }
    const name = newVendorName.trim()
    const kind = vendorKindForPaymentType(paymentType)
    setNewVendorSaving(true)
    try {
      const row = await createVendor({
        kind,
        name,
        inn: kind === 'transfer' ? newVendorInn.trim() : undefined,
        account_number: newVendorAccount.trim() || undefined,
      })
      message.success('Поставщик добавлен')
      setVendorRefId(row.id)
      setNewVendorOpen(false)
      setNewVendorName('')
      setNewVendorInn('')
      setNewVendorAccount('')
      await loadVendors('')
      // The new vendor stays among the options (its name is shown) even when the reloaded list leaves it out:
      // not yet in the search index, or outside the vendors allowed for the type.
      const created = { value: row.id, label: vendorOptionLabel({ ...row, kind: row.kind || kind }) }
      setVendorOptions((prev) => (prev.some((o) => o.value === row.id) ? prev : [created, ...prev]))
    } catch (e: unknown) {
      if (e instanceof ApiError && e.status === 403) {
        message.error('У вас нет прав на создание поставщика. Обратитесь к администратору.')
      } else {
        message.error(e instanceof Error ? e.message : 'Ошибка')
      }
    } finally {
      setNewVendorSaving(false)
    }
  }

  /** Opens «Новый договор» with an empty form in the request's currency (needs a chosen vendor). */
  const openNewContract = () => {
    if (!vendorRefId) {
      message.warning('Сначала выберите поставщика')
      return
    }
    setNcNumber('')
    setNcDateFrom('')
    setNcDateTo('')
    setNcAmount(null)
    setNcCurrency(currency || 'UZS')
    setNcTerms('')
    setNcAcc('')
    setNcFileList([])
    setNewContractOpen(true)
  }

  const saveNewContract = async () => {
    if (!vendorRefId) return
    const issues = newContractIssues()
    setNewContractAttempted(true)
    if (issues.length > 0) {
      notify(issues[0])
      return
    }
    const num = ncNumber.trim()
    const f = ncFileList[0]?.originFileObj as File
    setNewContractSaving(true)
    try {
      const created = await createContract({
        vendor: vendorRefId,
        contract_number: num,
        date_from: ncDateFrom.trim(),
        date_to: ncDateTo.trim() || undefined,
        contract_amount: ncAmount != null ? String(ncAmount) : undefined,
        currency: ncCurrency,
        contract_terms: ncTerms.trim(),
        acc_number: ncAcc.trim(),
        contract_file: f,
      })
      message.success('Договор создан')
      setNewContractOpen(false)
      const rows = await listContracts({ vendor: vendorRefId })
      setContractOptions(rows.map((r) => ({ value: r.id, label: contractOptionLabel(r) })))
      setContractRefId(created.id)
    } catch (e: unknown) {
      if (e instanceof ApiError && e.status === 403) {
        message.error('У вас нет прав на создание договора. Обратитесь к администратору.')
      } else {
        message.error(e instanceof Error ? e.message : 'Ошибка')
      }
    } finally {
      setNewContractSaving(false)
    }
  }

  return {
    loading,
    optionsError,
    reloadFormOptions,
    formOptions,
    step,
    stepItems,
    detailStep,
    requiresRequesterSelection,
    activePt,
    paymentType,
    setPaymentType,
    selectPaymentType,
    requesterId,
    setRequesterId,
    allowedRequesters,
    vendorRefId,
    setVendorRefId,
    selectVendor,
    vendorOptions,
    vendorSearchLoading,
    onVendorSearch,
    fetchVendorOptions,
    fetchVendorPage,
    contractsRequiredForPt,
    contractRefId,
    setContractRefId,
    contractOptions,
    contractLoading,
    contractLoadError,
    fetchContractOptions,
    description,
    setDescription,
    amount,
    setAmount,
    currency,
    setCurrency,
    currencyOptions,
    lockedCurrency,
    fundingHint,
    urgency,
    setUrgency,
    paymentPurpose,
    setPaymentPurpose,
    purposeOptions,
    transferPurposeHidden,
    transferHintText,
    billingDate,
    setBillingDate,
    amortizationEnabled,
    setAmortizationEnabled,
    amortizationMonths,
    setAmortizationMonths,
    attachmentFileList,
    setAttachmentFileList,
    submitting,
    goNext,
    goBack,
    submit,
    fieldErrors,
    newVendorOpen,
    setNewVendorOpen,
    newVendorName,
    setNewVendorName,
    newVendorInn,
    setNewVendorInn,
    newVendorAccount,
    setNewVendorAccount,
    newVendorSaving,
    saveNewVendor,
    newContractOpen,
    setNewContractOpen,
    openNewContract,
    newContractSaving,
    saveNewContract,
    ncNumber,
    setNcNumber,
    ncDateFrom,
    setNcDateFrom,
    ncDateTo,
    setNcDateTo,
    ncAmount,
    setNcAmount,
    ncCurrency,
    setNcCurrency,
    ncTerms,
    setNcTerms,
    ncAcc,
    setNcAcc,
    ncFileList,
    setNcFileList,
  }
}

export type RequestCreateForm = ReturnType<typeof useRequestCreateForm>
