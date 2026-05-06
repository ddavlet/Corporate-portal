import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  DatePicker,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Steps,
  Switch,
  Typography,
  Upload,
  message,
} from 'antd'
import type { Dayjs } from 'dayjs'
import type { UploadFile } from 'antd/es/upload/interface'
import { ArrowLeftOutlined, PlusOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import {
  createContract,
  createPortalRequest,
  createVendor,
  getRequestFormOptions,
  listContracts,
  listVendors,
  REQUEST_ATTACHMENT_MAX_FILES,
  type CreatedPortalRequest,
  type PortalRequestCreateBody,
  type RequestFormOptionsPaymentType,
  uploadRequestAttachment,
  validateRequestAttachment,
} from '../../lib/api'
import { labelBlockAboveField } from '../formSpacing'
import { clampToAllowedBillingMonth, isAllowedBillingMonth } from '../../lib/billingMonth'
import { monthStartTashkent } from '../../lib/tashkentTime'

function vendorKindForPaymentType(paymentType: string): 'cash' | 'transfer' {
  return paymentType === 'Наличные' ? 'cash' : 'transfer'
}

const tgPopupContainer = () => document.body

export type RequestCreatePageProps = {
  /** Базовый путь списка заявок без завершающего «/», например `/tg/requests` */
  requestsBasePath?: string
  /** Мобильная вёрстка для Telegram WebApp */
  variant?: 'portal' | 'telegram'
}

export function RequestCreatePage({ requestsBasePath = '/requests', variant = 'portal' }: RequestCreatePageProps) {
  const isTg = variant === 'telegram'
  const navigate = useNavigate()
  const [loading, setLoading] = useState(true)
  const [optionsError, setOptionsError] = useState<string | null>(null)
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
  const [vendorOptions, setVendorOptions] = useState<{ label: string; value: number }[]>([])
  const [vendorSearchLoading, setVendorSearchLoading] = useState(false)
  const [contractRefId, setContractRefId] = useState<number | null>(null)
  const [contractOptions, setContractOptions] = useState<{ label: string; value: number }[]>([])
  const [contractLoading, setContractLoading] = useState(false)

  const [description, setDescription] = useState('')
  const [amount, setAmount] = useState<number | null>(null)
  const [currency, setCurrency] = useState('UZS')
  const [urgency, setUrgency] = useState('Обычно')
  const [paymentPurpose, setPaymentPurpose] = useState<string | null>(null)
  const [billingDate, setBillingDate] = useState<Dayjs | null>(() => monthStartTashkent())
  const [amortizationEnabled, setAmortizationEnabled] = useState(false)
  const [amortizationMonths, setAmortizationMonths] = useState(2)
  const [attachments, setAttachments] = useState<File[]>([])

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

  const activePt = useMemo(
    () => formOptions.find((p) => p.payment_type === paymentType) || null,
    [formOptions, paymentType],
  )

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
  }, [])

  const loadVendors = useCallback(
    async (search: string) => {
      if (!paymentType) return
      const kind = vendorKindForPaymentType(paymentType)
      setVendorSearchLoading(true)
      try {
        const rows = await listVendors({ kind, search })
        let filtered = rows
        if (activePt?.vendor_ids?.length) {
          const allowed = new Set(activePt.vendor_ids)
          filtered = rows.filter((r) => allowed.has(r.id))
        }
        setVendorOptions(
          filtered.map((r) => ({
            value: r.id,
            label: r.kind === 'transfer' && r.inn ? `${r.name} (ИНН ${r.inn})` : r.name,
          })),
        )
      } catch {
        setVendorOptions([])
      } finally {
        setVendorSearchLoading(false)
      }
    },
    [paymentType, activePt],
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
      setPaymentPurpose(d.payment_purpose ?? null)
      setVendorRefId(d.vendor_ref ?? null)
    } else {
      setBillingDate((prev) => clampToAllowedBillingMonth(prev ?? monthStartTashkent()))
    }
  }, [step, paymentType, formOptions, detailStep])

  let searchTimer: ReturnType<typeof setTimeout> | undefined
  const onVendorSearch = (value: string) => {
    window.clearTimeout(searchTimer)
    searchTimer = setTimeout(() => void loadVendors(value), 300)
  }

  const contractsRequiredForPt = Boolean(contractsModuleEffective && activePt?.contracts_required)

  useEffect(() => {
    if (!contractsRequiredForPt || !vendorRefId) {
      setContractOptions([])
      setContractRefId(null)
      return
    }
    let cancelled = false
    setContractLoading(true)
    listContracts({ vendor: vendorRefId })
      .then((rows) => {
        if (cancelled) return
        setContractOptions(
          rows.map((r) => ({
            value: r.id,
            label: `${r.contract_number} (${r.date_from})${r.is_expired ? ' — просрочен' : ''}`,
          })),
        )
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
        }
      })
      .finally(() => {
        if (!cancelled) setContractLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [contractsRequiredForPt, vendorRefId])

  const purposeOptions = useMemo(() => {
    if (!activePt?.payment_purposes?.length) return []
    return activePt.payment_purposes.map((p) => ({
      value: p.name,
      label: `${p.name} → ${p.category}`,
    }))
  }, [activePt])

  const stepItems = useMemo(() => {
    if (requiresRequesterSelection) {
      return [{ title: 'Тип оплаты' }, { title: 'Заявитель' }, { title: 'Детали' }]
    }
    return [{ title: 'Тип оплаты' }, { title: 'Детали' }]
  }, [requiresRequesterSelection])

  const goNext = () => {
    if (step === 0 && !paymentType) {
      message.warning('Выберите тип оплаты')
      return
    }
    if (step === 1 && requiresRequesterSelection) {
      if (!paymentType || !activePt) {
        message.warning('Выберите тип оплаты')
        return
      }
      if (allowedRequesters.length === 0) {
        message.warning(
          'Для выбранного типа оплаты не настроены заявители. Укажите их в Настройки → Заявки — форма создания.',
        )
        return
      }
      if (requesterId == null) {
        message.warning('Выберите заявителя')
        return
      }
    }
    setStep((s) => Math.min(s + 1, detailStep))
  }

  const goBack = () => setStep((s) => Math.max(s - 1, 0))

  const submit = async () => {
    if (!paymentType) {
      message.error('Выберите тип оплаты')
      return
    }
    if (requiresRequesterSelection) {
      if ((activePt?.requesters?.length ?? 0) === 0) {
        message.error('Для выбранного типа оплаты не настроены заявители.')
        return
      }
      if (requesterId == null) {
        message.error('Выберите заявителя')
        return
      }
    }
    if (amount == null || amount <= 0) {
      message.warning('Укажите сумму')
      return
    }
    if (!billingDate || !isAllowedBillingMonth(billingDate)) {
      message.warning('Выберите допустимый месяц биллинга')
      return
    }
    if (purposeOptions.length > 0 && !paymentPurpose) {
      message.warning('Выберите назначение платежа')
      return
    }
    if (activePt?.vendor_ids?.length && !vendorRefId) {
      message.warning('Выберите поставщика из списка')
      return
    }
    if (contractsRequiredForPt && !contractRefId) {
      message.warning('Выберите договор')
      return
    }
    if (attachments.length > REQUEST_ATTACHMENT_MAX_FILES) {
      message.warning(`Можно прикрепить максимум ${REQUEST_ATTACHMENT_MAX_FILES} файлов`)
      return
    }
    for (const file of attachments) {
      const err = validateRequestAttachment(file)
      if (err) {
        message.warning(`${file.name}: ${err}`)
        return
      }
    }

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
      message.success('Заявка создана')
      const id = res.id
      if (typeof id === 'number') navigate(`${requestsBasePath}/${id}`)
      else navigate(requestsBasePath)
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : 'Ошибка сохранения')
    } finally {
      setSubmitting(false)
    }
  }

  const saveNewVendor = async () => {
    if (!paymentType) return
    const name = newVendorName.trim()
    if (!name) {
      message.warning('Укажите наименование')
      return
    }
    const kind = vendorKindForPaymentType(paymentType)
    if (kind === 'transfer' && !newVendorInn.trim()) {
      message.warning('ИНН обязателен для перечисления')
      return
    }
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
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : 'Ошибка')
    } finally {
      setNewVendorSaving(false)
    }
  }

  const saveNewContract = async () => {
    if (!vendorRefId) return
    const num = ncNumber.trim()
    if (!num) {
      message.warning('Укажите номер договора')
      return
    }
    if (!ncDateFrom.trim()) {
      message.warning('Укажите дату начала')
      return
    }
    if (ncAmount == null || ncAmount <= 0) {
      message.warning('Укажите сумму договора')
      return
    }
    const f = ncFileList[0]?.originFileObj as File | undefined
    setNewContractSaving(true)
    try {
      const created = await createContract({
        vendor: vendorRefId,
        contract_number: num,
        date_from: ncDateFrom.trim(),
        date_to: ncDateTo.trim() || undefined,
        contract_amount: String(ncAmount),
        currency: ncCurrency,
        contract_terms: ncTerms.trim(),
        acc_number: ncAcc.trim(),
        contract_file: f,
      })
      message.success('Договор создан')
      setNewContractOpen(false)
      const rows = await listContracts({ vendor: vendorRefId })
      setContractOptions(
        rows.map((r) => ({
          value: r.id,
          label: `${r.contract_number} (${r.date_from})${r.is_expired ? ' — просрочен' : ''}`,
        })),
      )
      setContractRefId(created.id)
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : 'Ошибка')
    } finally {
      setNewContractSaving(false)
    }
  }

  return (
    <div className={isTg ? 'tg-create-page' : undefined}>
      <Card className={isTg ? 'tg-create-card' : undefined} styles={{ body: isTg ? { padding: '16px 16px 24px' } : undefined }}>
        <Space direction="vertical" size={isTg ? 'middle' : 'large'} style={{ display: 'flex' }}>
          <Button
            type="link"
            icon={<ArrowLeftOutlined />}
            onClick={() => navigate(requestsBasePath)}
            style={{ padding: isTg ? '8px 0' : 0, minHeight: isTg ? 44 : undefined, alignSelf: 'flex-start' }}
          >
            К списку заявок
          </Button>
          <Typography.Title level={4} style={{ margin: 0, fontSize: isTg ? 20 : undefined }}>
            Новая заявка
          </Typography.Title>
        {optionsError ? <Alert type="error" showIcon message={optionsError} /> : null}
        {!loading && !optionsError && formOptions.length === 0 ? (
          <Alert
            type="warning"
            showIcon
            message="Форма не настроена"
            description="Администратор должен включить типы оплаты в Настройки → Заявки — форма создания."
          />
        ) : null}

        <Steps
          size="small"
          current={step}
          items={stepItems}
          direction={isTg ? 'vertical' : 'horizontal'}
          className={isTg ? 'tg-steps' : undefined}
        />

        {step === 0 ? (
          <div className={isTg ? 'tg-field-block' : undefined}>
            <Typography.Text strong style={labelBlockAboveField}>
              Тип оплаты
            </Typography.Text>
            <Select
              placeholder="Выберите тип оплаты"
              size={isTg ? 'large' : undefined}
              style={{ width: '100%', maxWidth: isTg ? undefined : 400 }}
              value={paymentType || undefined}
              onChange={(v) => {
                setPaymentType(v)
                setRequesterId(null)
                setVendorRefId(null)
                setContractRefId(null)
                setPaymentPurpose(null)
                setAmortizationEnabled(false)
                setAmortizationMonths(2)
              }}
              options={formOptions.map((p) => ({ value: p.payment_type, label: p.payment_type }))}
              getPopupContainer={isTg ? tgPopupContainer : undefined}
              popupMatchSelectWidth={isTg ? true : undefined}
            />
          </div>
        ) : null}

        {step === 1 && requiresRequesterSelection ? (
          <div className={isTg ? 'tg-field-block' : undefined}>
            <Typography.Text strong style={labelBlockAboveField}>
              Заявитель
            </Typography.Text>
            {allowedRequesters.length === 0 ? (
              <Alert
                type="warning"
                showIcon
                style={{ maxWidth: isTg ? undefined : 560, borderRadius: 12 }}
                message="Для этого типа оплаты не выбраны заявители"
                description="Укажите заявителей для типа оплаты в Настройки → Заявки — форма создания."
              />
            ) : (
              <Select
                placeholder="Выберите заявителя"
                size={isTg ? 'large' : undefined}
                style={{ width: '100%', maxWidth: isTg ? undefined : 400 }}
                value={requesterId ?? undefined}
                onChange={(v) => setRequesterId(v)}
                options={allowedRequesters.map((r) => ({ value: r.id, label: r.username }))}
                showSearch
                optionFilterProp="label"
                getPopupContainer={isTg ? tgPopupContainer : undefined}
                popupMatchSelectWidth={isTg ? true : undefined}
              />
            )}
          </div>
        ) : null}

        {step === detailStep ? (
          <Space direction="vertical" size="middle" style={{ display: 'flex', width: '100%' }}>
            {isTg ? (
              <>
                <div className="tg-field-block">
                  <Typography.Text strong style={labelBlockAboveField}>
                    Сумма
                  </Typography.Text>
                  <InputNumber
                    size="large"
                    style={{ display: 'block', width: '100%' }}
                    min={0}
                    value={amount ?? undefined}
                    onChange={(v) => setAmount(typeof v === 'number' ? v : null)}
                  />
                </div>
                <div className="tg-field-block">
                  <Typography.Text strong style={labelBlockAboveField}>
                    Валюта
                  </Typography.Text>
                  <Select
                    size="large"
                    style={{ display: 'block', width: '100%' }}
                    value={currency}
                    onChange={setCurrency}
                    options={['UZS', 'USD', 'EUR', 'RUB'].map((c) => ({ value: c, label: c }))}
                    getPopupContainer={tgPopupContainer}
                    popupMatchSelectWidth
                  />
                </div>
                <div className="tg-field-block">
                  <Typography.Text strong style={labelBlockAboveField}>
                    Срочность
                  </Typography.Text>
                  <Select
                    size="large"
                    style={{ display: 'block', width: '100%' }}
                    value={urgency}
                    onChange={setUrgency}
                    options={[
                      { value: 'Низко', label: 'Низко' },
                      { value: 'Обычно', label: 'Обычно' },
                      { value: 'Срочно', label: 'Срочно' },
                    ]}
                    getPopupContainer={tgPopupContainer}
                    popupMatchSelectWidth
                  />
                </div>
                <div className="tg-field-block">
                  <Typography.Text strong style={labelBlockAboveField}>
                    Месяц биллинга
                  </Typography.Text>
                  <DatePicker
                    size="large"
                    picker="month"
                    style={{ display: 'block', width: '100%' }}
                    format="MM.YYYY"
                    value={billingDate}
                    onChange={(v) => setBillingDate(v ? v.startOf('month') : null)}
                    disabledDate={(current) => !current || !isAllowedBillingMonth(current)}
                    getPopupContainer={tgPopupContainer}
                    inputReadOnly
                  />
                </div>
                <div className="tg-field-block">
                  <Space align="center" size="middle">
                    <Typography.Text strong>Амортизировать расход</Typography.Text>
                    <Switch
                      checked={amortizationEnabled}
                      onChange={(checked) => {
                        setAmortizationEnabled(checked)
                        if (!checked) setAmortizationMonths(2)
                      }}
                    />
                  </Space>
                </div>
                {amortizationEnabled ? (
                  <div className="tg-field-block">
                    <Typography.Text strong style={labelBlockAboveField}>
                      Срок амортизации (мес.)
                    </Typography.Text>
                    <Select
                      size="large"
                      style={{ display: 'block', width: '100%' }}
                      value={amortizationMonths}
                      onChange={setAmortizationMonths}
                      options={[2, 3, 4, 5, 6].map((m) => ({ value: m, label: `${m}` }))}
                      getPopupContainer={tgPopupContainer}
                      popupMatchSelectWidth
                    />
                  </div>
                ) : null}
              </>
            ) : (
              <Space wrap size={16}>
                <div>
                  <Typography.Text strong style={labelBlockAboveField}>
                    Сумма
                  </Typography.Text>
                  <InputNumber
                    style={{ display: 'block', width: 160 }}
                    min={0}
                    value={amount ?? undefined}
                    onChange={(v) => setAmount(typeof v === 'number' ? v : null)}
                  />
                </div>
                <div>
                  <Typography.Text strong style={labelBlockAboveField}>
                    Валюта
                  </Typography.Text>
                  <Select
                    style={{ display: 'block', width: 120 }}
                    value={currency}
                    onChange={setCurrency}
                    options={['UZS', 'USD', 'EUR', 'RUB'].map((c) => ({ value: c, label: c }))}
                  />
                </div>
                <div>
                  <Typography.Text strong style={labelBlockAboveField}>
                    Срочность
                  </Typography.Text>
                  <Select
                    style={{ display: 'block', width: 180 }}
                    value={urgency}
                    onChange={setUrgency}
                    options={[
                      { value: 'Низко', label: 'Низко' },
                      { value: 'Обычно', label: 'Обычно' },
                      { value: 'Срочно', label: 'Срочно' },
                    ]}
                  />
                </div>
                <div>
                  <Typography.Text strong style={labelBlockAboveField}>
                    Месяц биллинга
                  </Typography.Text>
                  <DatePicker
                    picker="month"
                    style={{ display: 'block', maxWidth: 280 }}
                    format="MMMM YYYY"
                    value={billingDate}
                    onChange={(v) => setBillingDate(v ? v.startOf('month') : null)}
                    disabledDate={(current) => !current || !isAllowedBillingMonth(current)}
                  />
                </div>
                <div>
                  <Typography.Text strong style={labelBlockAboveField}>
                    Амортизировать расход
                  </Typography.Text>
                  <Switch
                    checked={amortizationEnabled}
                    onChange={(checked) => {
                      setAmortizationEnabled(checked)
                      if (!checked) setAmortizationMonths(2)
                    }}
                  />
                </div>
                {amortizationEnabled ? (
                  <div>
                    <Typography.Text strong style={labelBlockAboveField}>
                      Срок амортизации (мес.)
                    </Typography.Text>
                    <Select
                      style={{ display: 'block', width: 180 }}
                      value={amortizationMonths}
                      onChange={setAmortizationMonths}
                      options={[2, 3, 4, 5, 6].map((m) => ({ value: m, label: `${m}` }))}
                    />
                  </div>
                ) : null}
              </Space>
            )}
            {purposeOptions.length > 0 ? (
              <div className={isTg ? 'tg-field-block' : undefined}>
                <Typography.Text strong style={labelBlockAboveField}>
                  Назначение платежа
                </Typography.Text>
                <Select
                  placeholder="Выберите назначение"
                  size={isTg ? 'large' : undefined}
                  style={{ display: 'block', width: '100%', maxWidth: isTg ? undefined : 560 }}
                  value={paymentPurpose || undefined}
                  onChange={setPaymentPurpose}
                  options={purposeOptions}
                  getPopupContainer={isTg ? tgPopupContainer : undefined}
                  popupMatchSelectWidth={isTg ? true : undefined}
                />
              </div>
            ) : null}
            <div className={isTg ? 'tg-field-block' : undefined}>
              <Space align="center" size="middle" wrap style={{ marginBottom: 8 }}>
                <Typography.Text strong>Поставщик</Typography.Text>
                <Button type="link" icon={<PlusOutlined />} onClick={() => setNewVendorOpen(true)} style={{ paddingInline: 0 }}>
                  Новый поставщик
                </Button>
              </Space>
              <Select
                placeholder="Поиск по названию / ИНН"
                size={isTg ? 'large' : undefined}
                style={{ display: 'block', width: '100%', maxWidth: isTg ? undefined : 560 }}
                showSearch
                filterOption={false}
                loading={vendorSearchLoading}
                value={vendorRefId ?? undefined}
                onChange={(v) => {
                  setVendorRefId(v)
                  setContractRefId(null)
                }}
                onSearch={onVendorSearch}
                options={vendorOptions}
                allowClear
                getPopupContainer={isTg ? tgPopupContainer : undefined}
                popupMatchSelectWidth={isTg ? true : undefined}
              />
            </div>
            {contractsRequiredForPt ? (
              <div className={isTg ? 'tg-field-block' : undefined}>
                <Space align="center" size="middle" wrap style={{ marginBottom: 8 }}>
                  <Typography.Text strong>Договор</Typography.Text>
                  <Button
                    type="link"
                    icon={<PlusOutlined />}
                    disabled={!vendorRefId}
                    onClick={() => {
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
                    }}
                    style={{ paddingInline: 0 }}
                  >
                    Новый договор
                  </Button>
                </Space>
                <Select
                  placeholder={vendorRefId ? 'Выберите договор' : 'Сначала выберите поставщика'}
                  size={isTg ? 'large' : undefined}
                  style={{ display: 'block', width: '100%', maxWidth: isTg ? undefined : 560 }}
                  loading={contractLoading}
                  value={contractRefId ?? undefined}
                  onChange={(v) => setContractRefId(v)}
                  options={contractOptions}
                  allowClear
                  getPopupContainer={isTg ? tgPopupContainer : undefined}
                  popupMatchSelectWidth={isTg ? true : undefined}
                />
              </div>
            ) : null}
            <div className={isTg ? 'tg-field-block' : undefined}>
              <Typography.Text strong style={labelBlockAboveField}>
                Описание
              </Typography.Text>
              <Input.TextArea
                style={{ maxWidth: isTg ? undefined : 560 }}
                rows={isTg ? 4 : 3}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
            </div>
            <div className={isTg ? 'tg-field-block' : undefined}>
              <Typography.Text strong style={labelBlockAboveField}>
                Вложения
              </Typography.Text>
              <input type="file" multiple onChange={(e) => setAttachments(Array.from(e.target.files || []))} style={{ width: '100%' }} />
              <Typography.Text type="secondary" style={{ display: 'block', marginTop: 6 }}>
                {attachments.length > 0 ? `Выбрано файлов: ${attachments.length}` : 'Файлы не выбраны'}
              </Typography.Text>
            </div>
          </Space>
        ) : null}

        {!isTg ? (
          <Space>
            {step > 0 ? <Button onClick={goBack}>Назад</Button> : null}
            {step < detailStep ? (
              <Button type="primary" onClick={goNext} disabled={loading || formOptions.length === 0}>
                Далее
              </Button>
            ) : (
              <Button type="primary" loading={submitting} onClick={() => void submit()}>
                Создать заявку
              </Button>
            )}
          </Space>
        ) : null}
      </Space>

      <Modal
        title="Новый поставщик"
        open={newVendorOpen}
        onCancel={() => setNewVendorOpen(false)}
        onOk={() => void saveNewVendor()}
        confirmLoading={newVendorSaving}
        okText="Сохранить"
        centered
        width={isTg ? 'min(calc(100vw - 24px), 400px)' : undefined}
        styles={
          isTg
            ? {
                body: { maxHeight: 'min(72dvh, 520px)', overflowY: 'auto' },
              }
            : undefined
        }
        getContainer={isTg ? () => document.body : undefined}
      >
        <Typography.Paragraph type="secondary">
          Тип: {paymentType === 'Наличные' ? 'наличные' : 'перечисление'} (по выбранному типу оплаты заявки).
        </Typography.Paragraph>
        <Form layout="vertical">
          <Form.Item label="Наименование" required>
            <Input value={newVendorName} onChange={(e) => setNewVendorName(e.target.value)} />
          </Form.Item>
          {paymentType && paymentType !== 'Наличные' ? (
            <Form.Item label="ИНН" required>
              <Input value={newVendorInn} onChange={(e) => setNewVendorInn(e.target.value)} />
            </Form.Item>
          ) : null}
          <Form.Item label="Расчётный счёт (необязательно)">
            <Input value={newVendorAccount} onChange={(e) => setNewVendorAccount(e.target.value)} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="Новый договор"
        open={newContractOpen}
        onCancel={() => setNewContractOpen(false)}
        onOk={() => void saveNewContract()}
        confirmLoading={newContractSaving}
        okText="Сохранить"
        centered
        width={isTg ? 'min(calc(100vw - 24px), 440px)' : 520}
        getContainer={isTg ? () => document.body : undefined}
      >
        <Typography.Paragraph type="secondary">
          Поставщик: текущий выбор в заявке (из справочника).
        </Typography.Paragraph>
        <Form layout="vertical">
          <Form.Item label="Номер договора" required>
            <Input value={ncNumber} onChange={(e) => setNcNumber(e.target.value)} />
          </Form.Item>
          <Space wrap>
            <Form.Item label="Дата с" required>
              <Input type="date" value={ncDateFrom} onChange={(e) => setNcDateFrom(e.target.value)} />
            </Form.Item>
            <Form.Item label="Дата по">
              <Input type="date" value={ncDateTo} onChange={(e) => setNcDateTo(e.target.value)} />
            </Form.Item>
          </Space>
          <Space wrap>
            <Form.Item label="Сумма" required>
              <InputNumber min={0.01} step={0.01} value={ncAmount ?? undefined} onChange={(v) => setNcAmount(typeof v === 'number' ? v : null)} />
            </Form.Item>
            <Form.Item label="Валюта">
              <Select
                style={{ width: 120 }}
                value={ncCurrency}
                onChange={setNcCurrency}
                options={['UZS', 'USD', 'EUR', 'RUB'].map((c) => ({ value: c, label: c }))}
              />
            </Form.Item>
          </Space>
          <Form.Item label="Расчётный счёт">
            <Input value={ncAcc} onChange={(e) => setNcAcc(e.target.value)} />
          </Form.Item>
          <Form.Item label="Условия">
            <Input.TextArea rows={2} value={ncTerms} onChange={(e) => setNcTerms(e.target.value)} />
          </Form.Item>
          <Form.Item label="Файл">
            <Upload maxCount={1} fileList={ncFileList} beforeUpload={() => false} onChange={({ fileList }) => setNcFileList(fileList)}>
              <Button>Выбрать файл</Button>
            </Upload>
          </Form.Item>
        </Form>
      </Modal>
    </Card>

      {isTg ? (
        <div className="tg-sticky-actions">
          {step > 0 ? (
            <Button size="large" onClick={goBack}>
              Назад
            </Button>
          ) : (
            <span style={{ width: 88, flexShrink: 0 }} aria-hidden />
          )}
          {step < detailStep ? (
            <Button type="primary" size="large" onClick={goNext} disabled={loading || formOptions.length === 0}>
              Далее
            </Button>
          ) : (
            <Button type="primary" size="large" loading={submitting} onClick={() => void submit()}>
              Создать заявку
            </Button>
          )}
        </div>
      ) : null}
    </div>
  )
}
