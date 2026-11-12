import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { Alert, Button, DatePicker, Input, InputNumber, Segmented, Select, Switch, Typography, Upload, theme } from 'antd'
import { ArrowLeftOutlined, CheckOutlined, CloseOutlined, PlusOutlined, RightOutlined } from '@ant-design/icons'
import { isAllowedBillingMonth } from '../../lib/billingMonth'
import { fundingWalletLabel } from '../../lib/requestPaymentTypes'
import { MobilePickerSheet, PICKER_PAGE_SIZE } from '../MobilePickerSheet'
import { MobileStateWidget } from '../MobileStateWidget'
import { MobileActionsTheme } from './mobileActionsTheme'
import { Field } from './MobileFormFieldWidget'
import { NewContractSheet } from './NewContractSheet'
import { NewVendorSheet } from './NewVendorSheet'
import { StepsProgressWidget } from './StepsProgressWidget'
import { useRequestCreateForm, type RequestCreateOption } from './useRequestCreateForm'

export type RequestCreateMobilePageProps = {
  /** Base path of the requests list without the trailing «/». */
  requestsBasePath?: string
}

const URGENCY_OPTIONS = ['Низко', 'Обычно', 'Срочно']

type Requester = { id: number; username: string }

/**
 * `/requests/new` on a phone: a full-screen wizard over the shell. «Закрыть» on the first step and «Назад» further on,
 * a progress of the steps («Заявитель» only for a tenant admin or director), fields one per row with their errors
 * under them, the action pinned to the bottom. Vendor, contract and requester are picked on full-screen search
 * screens; «Новый поставщик» and «Новый договор» are bottom sheets. The form state and rules are the desktop's
 * (useRequestCreateForm); the new request opens in its card.
 *
 * The system «Назад» (Android gesture, browser button) does what the wizard's own «Назад» does instead of leaving
 * the form: from the second step on the wizard keeps one extra history entry of the same address (a guard); going
 * back from it closes the open picker or sheet, or returns to the previous step, and the guard is put back.
 */
export function RequestCreateMobilePage({ requestsBasePath = '/requests' }: RequestCreateMobilePageProps) {
  const { token } = theme.useToken()
  const navigate = useNavigate()
  const location = useLocation()
  // Back-guard bookkeeping (see above): whether this wizard has pushed the guard entry, whether the history was on
  // the guard at the previous location, and the created request waiting for the guard to be left.
  const guardPushedRef = useRef(false)
  const onGuardEntry = Boolean((location.state as { requestCreateGuard?: boolean } | null)?.requestCreateGuard)
  const wasOnGuardRef = useRef(onGuardEntry)
  const createdIdRef = useRef<number | null>(null)
  const openCreated = (id: number) =>
    navigate(`${requestsBasePath}/${id}`, { replace: true, state: { justCreated: true } })
  const form = useRequestCreateForm({
    requestsBasePath,
    // Replace the wizard: «Назад» from the new card leads to the list, not to an empty form. The guard entry is left
    // first, so the card replaces the wizard's own entry.
    onCreated: (id) => {
      if (guardPushedRef.current && wasOnGuardRef.current) {
        guardPushedRef.current = false
        createdIdRef.current = id
        navigate(-1)
      } else openCreated(id)
    },
  })
  const [vendorPickerOpen, setVendorPickerOpen] = useState(false)
  const [contractPickerOpen, setContractPickerOpen] = useState(false)
  const [requesterPickerOpen, setRequesterPickerOpen] = useState(false)
  const [pickedVendor, setPickedVendor] = useState<RequestCreateOption | null>(null)
  const bodyRef = useRef<HTMLDivElement>(null)

  const { step, detailStep, fieldErrors: errors } = form
  const isDetails = step === detailStep
  const isRequesterStep = form.requiresRequesterSelection && step === 1

  const guardNeeded = step > 0

  /** Closes the picker or sheet on top of the wizard; false when none is open. */
  const closeTopOverlay = () => {
    if (form.newContractOpen) form.setNewContractOpen(false)
    else if (form.newVendorOpen) form.setNewVendorOpen(false)
    else if (contractPickerOpen) setContractPickerOpen(false)
    else if (vendorPickerOpen) setVendorPickerOpen(false)
    else if (requesterPickerOpen) setRequesterPickerOpen(false)
    else return false
    return true
  }

  useEffect(() => {
    const wasOnGuard = wasOnGuardRef.current
    wasOnGuardRef.current = onGuardEntry
    const pushGuard = () => {
      guardPushedRef.current = true
      navigate(`${location.pathname}${location.search}`, { state: { requestCreateGuard: true } })
    }
    const createdId = createdIdRef.current
    if (createdId != null) {
      if (onGuardEntry) return
      createdIdRef.current = null
      openCreated(createdId)
      return
    }
    if (onGuardEntry) {
      // Back on the first step through the wizard's own «Назад»: the guard is not needed any more.
      if (!guardNeeded) {
        if (guardPushedRef.current) {
          guardPushedRef.current = false
          navigate(-1)
        } else {
          // A guard of an earlier page load (a reload on a later step): drop the mark, stay on the address.
          navigate(`${location.pathname}${location.search}`, { replace: true, state: null })
        }
      }
      return
    }
    if (wasOnGuard && guardPushedRef.current) {
      // The system «Назад» from the guard: one step of the wizard back, then guard again if still needed.
      guardPushedRef.current = false
      const closed = closeTopOverlay()
      if (!closed) form.goBack()
      if (closed || step - 1 > 0) pushGuard()
      return
    }
    if (guardNeeded && !guardPushedRef.current) pushGuard()
    // Runs on a new location and when the guard becomes (un)needed; the rest is read from this render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.key, guardNeeded])

  // Every step starts at its top.
  useEffect(() => {
    if (bodyRef.current) bodyRef.current.scrollTop = 0
  }, [step])

  // A refused step or submit: bring the first field with an error into view (it renders on the next frame).
  const scrollToFirstError = () => {
    requestAnimationFrame(() => {
      bodyRef.current?.querySelector('[role="alert"]')?.scrollIntoView?.({ block: 'center', behavior: 'smooth' })
    })
  }

  const close = () => {
    // An earlier page of the portal in this tab (the list): go back to it, so it restores its state.
    const idx = (window.history.state as { idx?: number } | null)?.idx
    if (typeof idx === 'number' && idx > 0) navigate(-1)
    else navigate(requestsBasePath, { replace: true })
  }

  const vendorLabel =
    form.vendorOptions.find((o) => o.value === form.vendorRefId)?.label ??
    (pickedVendor && pickedVendor.value === form.vendorRefId ? pickedVendor.label : null)
  const contractLabel = form.contractOptions.find((o) => o.value === form.contractRefId)?.label ?? null
  const requesterLabel = form.allowedRequesters.find((r) => r.id === form.requesterId)?.username ?? null

  // The picker asks the server itself: its own loading and error with a retry, never a stale or empty snapshot.
  const loadContracts = async (search: string) => {
    const needle = search.trim().toLowerCase()
    const options = await form.fetchContractOptions()
    return options.filter((o) => !needle || o.label.toLowerCase().includes(needle))
  }
  const loadVendors = (search: string) => form.fetchVendorPage(search, PICKER_PAGE_SIZE)
  const loadRequesters = async (search: string) => {
    const needle = search.trim().toLowerCase()
    return form.allowedRequesters
      .filter((r) => !needle || r.username.toLowerCase().includes(needle))
      .slice(0, PICKER_PAGE_SIZE)
  }

  const optionsReady = !form.loading && !form.optionsError && form.formOptions.length > 0

  let content: ReactNode
  if (form.loading) {
    content = <MobileStateWidget state="loading" rows={2} />
  } else if (form.optionsError) {
    content = (
      <MobileStateWidget
        state="error"
        title="Не удалось открыть форму"
        description={form.optionsError}
        onRetry={form.reloadFormOptions}
      />
    )
  } else if (form.formOptions.length === 0) {
    content = (
      <MobileStateWidget
        state="empty"
        title="Форма не настроена"
        description="Администратор должен включить типы оплаты в Настройки → Заявки — форма создания."
      />
    )
  } else if (step === 0) {
    content = (
      <Field label="Тип оплаты" labelId="create-payment-type-label" error={errors.paymentType} errorId="create-payment-type-error">
        <div
          role="radiogroup"
          aria-labelledby="create-payment-type-label"
          aria-describedby={errors.paymentType ? 'create-payment-type-error' : undefined}
          style={{ display: 'grid', gap: 8 }}
        >
          {form.formOptions.map((p) => {
            const selected = p.payment_type === form.paymentType
            return (
              <button
                key={p.payment_type}
                type="button"
                role="radio"
                aria-checked={selected}
                className="m-list-row"
                onClick={() => {
                  if (!selected) form.selectPaymentType(p.payment_type)
                }}
                style={{
                  border: `1px solid ${selected ? token.colorPrimary : token.colorBorder}`,
                  borderRadius: token.borderRadiusLG,
                  background: selected ? token.colorPrimaryBg : token.colorBgContainer,
                }}
              >
                <span style={{ flex: 1, minWidth: 0, overflowWrap: 'anywhere' }}>{p.payment_type}</span>
                {selected ? <CheckOutlined aria-hidden style={{ color: token.colorPrimaryActive }} /> : null}
              </button>
            )
          })}
        </div>
      </Field>
    )
  } else if (isRequesterStep) {
    content =
      form.allowedRequesters.length === 0 ? (
        <Alert
          type="warning"
          showIcon
          message="Для этого типа оплаты не выбраны заявители"
          description="Укажите заявителей для типа оплаты в Настройки → Заявки — форма создания."
        />
      ) : (
        <PickerField
          id="create-requester"
          label="Заявитель"
          value={requesterLabel}
          placeholder="Выберите заявителя"
          error={errors.requester}
          onOpen={() => setRequesterPickerOpen(true)}
        />
      )
  } else {
    content = (
      <>
        <Field label="Сумма" htmlFor="create-amount" error={errors.amount} errorId="create-amount-error">
          <InputNumber
            id="create-amount"
            style={{ width: '100%' }}
            min={0}
            inputMode="decimal"
            status={errors.amount ? 'error' : undefined}
            aria-invalid={errors.amount ? true : undefined}
            aria-describedby={errors.amount ? 'create-amount-error' : undefined}
            value={form.amount ?? undefined}
            onChange={(v) => form.setAmount(typeof v === 'number' ? v : null)}
          />
        </Field>
        {form.fundingHint ? (
          <Typography.Text style={{ color: token.colorTextSecondary }}>
            Списание: {fundingWalletLabel(form.fundingHint, form.currency)}
          </Typography.Text>
        ) : null}
        <Field label="Валюта" htmlFor="create-currency">
          <Select
            id="create-currency"
            style={{ width: '100%' }}
            value={form.currency}
            onChange={form.setCurrency}
            disabled={Boolean(form.lockedCurrency)}
            options={form.currencyOptions}
          />
        </Field>
        <Field label="Срочность" labelId="create-urgency-label">
          <Segmented
            block
            aria-labelledby="create-urgency-label"
            value={form.urgency}
            onChange={(v) => form.setUrgency(String(v))}
            options={URGENCY_OPTIONS}
          />
        </Field>
        <Field label="Месяц биллинга" htmlFor="create-billing-month" error={errors.billingDate} errorId="create-billing-error">
          <DatePicker
            id="create-billing-month"
            picker="month"
            format="MMMM YYYY"
            style={{ width: '100%' }}
            status={errors.billingDate ? 'error' : undefined}
            aria-invalid={errors.billingDate ? true : undefined}
            aria-describedby={errors.billingDate ? 'create-billing-error' : undefined}
            value={form.billingDate}
            onChange={(v) => form.setBillingDate(v ? v.startOf('month') : null)}
            disabledDate={(current) => !current || !isAllowedBillingMonth(current)}
            inputReadOnly
          />
        </Field>
        {form.purposeOptions.length > 0 ? (
          <Field label="Назначение платежа" htmlFor="create-purpose" error={errors.paymentPurpose} errorId="create-purpose-error">
            <Select
              id="create-purpose"
              placeholder="Выберите назначение"
              style={{ width: '100%' }}
              status={errors.paymentPurpose ? 'error' : undefined}
              aria-invalid={errors.paymentPurpose ? true : undefined}
              aria-describedby={errors.paymentPurpose ? 'create-purpose-error' : undefined}
              value={form.paymentPurpose || undefined}
              onChange={form.setPaymentPurpose}
              options={form.purposeOptions}
            />
          </Field>
        ) : null}
        {form.transferPurposeHidden ? (
          <Typography.Text type="secondary" style={{ display: 'block' }}>
            {form.transferHintText}
          </Typography.Text>
        ) : null}
        <PickerField
          id="create-vendor"
          label="Поставщик"
          value={vendorLabel}
          placeholder="Выберите поставщика"
          error={errors.vendor}
          onOpen={() => setVendorPickerOpen(true)}
        />
        {form.contractsRequiredForPt ? (
          <PickerField
            id="create-contract"
            label="Договор"
            value={contractLabel}
            placeholder={
              !form.vendorRefId
                ? 'Сначала выберите поставщика'
                : form.contractLoading
                  ? 'Загружаем договоры…'
                  : form.contractLoadError
                    ? 'Не удалось загрузить договоры, откройте ещё раз'
                    : 'Выберите договор'
            }
            disabled={!form.vendorRefId || form.contractLoading}
            error={errors.contract}
            onOpen={() => setContractPickerOpen(true)}
          />
        ) : null}
        <Field label="Описание" htmlFor="create-description">
          <Input.TextArea
            id="create-description"
            autoSize={{ minRows: 3, maxRows: 8 }}
            value={form.description}
            onChange={(e) => form.setDescription(e.target.value)}
          />
        </Field>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, minHeight: 44 }}>
          <label htmlFor="create-amortization" style={{ fontWeight: 600 }}>
            Амортизировать расход
          </label>
          <Switch
            id="create-amortization"
            checked={form.amortizationEnabled}
            onChange={(checked) => {
              form.setAmortizationEnabled(checked)
              if (!checked) form.setAmortizationMonths(2)
            }}
          />
        </div>
        {form.amortizationEnabled ? (
          <Field label="Срок амортизации (мес.)" htmlFor="create-amortization-months">
            <Select
              id="create-amortization-months"
              style={{ width: '100%' }}
              value={form.amortizationMonths}
              onChange={form.setAmortizationMonths}
              options={[2, 3, 4, 5, 6].map((m) => ({ value: m, label: `${m}` }))}
            />
          </Field>
        ) : null}
        <Field label="Вложения" labelId="create-attachments-label" error={errors.attachments} errorId="create-attachments-error">
          <Upload
            multiple
            beforeUpload={() => false}
            fileList={form.attachmentFileList}
            onChange={({ fileList }) => form.setAttachmentFileList(fileList)}
          >
            <Button icon={<PlusOutlined />} aria-describedby="create-attachments-label">
              Выбрать файлы
            </Button>
          </Upload>
        </Field>
      </>
    )
  }

  return (
    <div className="m-fullscreen m-root" data-testid="request-create-mobile" style={{ background: token.colorBgLayout }}>
      <header
        className="m-header"
        style={{ position: 'static', background: token.colorBgContainer, borderBottom: `1px solid ${token.colorBorderSecondary}` }}
      >
        {step === 0 ? (
          <Button type="text" className="m-header__button" icon={<CloseOutlined />} aria-label="Закрыть" onClick={close} />
        ) : (
          <Button type="text" className="m-header__button" icon={<ArrowLeftOutlined />} aria-label="Назад" onClick={form.goBack} />
        )}
        <h1 className="m-header__title m-ellipsis">Новая заявка</h1>
      </header>

      <StepsProgressWidget titles={form.stepItems.map((s) => s.title)} current={step} />

      <div ref={bodyRef} className="m-fullscreen__body">
        <div style={{ display: 'grid', gap: 16, padding: 16, minWidth: 0 }}>{content}</div>
      </div>

      <MobileActionsTheme>
        <div
          className="m-bottom-bar"
          style={{ position: 'static', background: token.colorBgContainer, borderTop: `1px solid ${token.colorBorderSecondary}` }}
        >
          {isDetails ? (
            <Button
              type="primary"
              block
              style={{ height: 44 }}
              loading={form.submitting}
              onClick={() => void form.submit().then(scrollToFirstError)}
            >
              Создать заявку
            </Button>
          ) : (
            <Button
              type="primary"
              block
              style={{ height: 44 }}
              disabled={!optionsReady}
              onClick={() => {
                form.goNext()
                scrollToFirstError()
              }}
            >
              Далее
            </Button>
          )}
        </div>
      </MobileActionsTheme>

      <MobilePickerSheet<RequestCreateOption>
        open={vendorPickerOpen}
        title="Поставщик"
        onClose={() => setVendorPickerOpen(false)}
        load={loadVendors}
        getKey={(o) => o.value}
        renderItem={(o) => o.label}
        selectedKey={form.vendorRefId}
        searchPlaceholder="Поиск по названию / ИНН"
        createLabel="Новый поставщик"
        onCreate={(search) => {
          setVendorPickerOpen(false)
          // A search of digits is an INN, anything else a name: the new vendor starts with it.
          if (/^\d+$/.test(search)) form.setNewVendorInn(search)
          else if (search) form.setNewVendorName(search)
          form.setNewVendorOpen(true)
        }}
        onSelect={(o) => {
          setPickedVendor(o)
          if (o.value !== form.vendorRefId) form.selectVendor(o.value)
          setVendorPickerOpen(false)
        }}
      />

      <MobilePickerSheet<RequestCreateOption>
        open={contractPickerOpen}
        title="Договор"
        onClose={() => setContractPickerOpen(false)}
        load={loadContracts}
        getKey={(o) => o.value}
        renderItem={(o) => o.label}
        selectedKey={form.contractRefId}
        searchPlaceholder="Поиск договора"
        emptyText="Договоров с этим поставщиком нет"
        createLabel="Новый договор"
        onCreate={() => {
          setContractPickerOpen(false)
          form.openNewContract()
        }}
        onSelect={(o) => {
          form.setContractRefId(o.value)
          setContractPickerOpen(false)
        }}
      />

      <MobilePickerSheet<Requester>
        open={requesterPickerOpen}
        title="Заявитель"
        onClose={() => setRequesterPickerOpen(false)}
        load={loadRequesters}
        getKey={(r) => r.id}
        renderItem={(r) => r.username}
        selectedKey={form.requesterId}
        searchPlaceholder="Поиск заявителя"
        onSelect={(r) => {
          form.setRequesterId(r.id)
          setRequesterPickerOpen(false)
        }}
      />

      <NewVendorSheet form={form} />
      <NewContractSheet form={form} vendorLabel={vendorLabel} />
    </div>
  )
}

type PickerFieldProps = {
  id: string
  label: string
  value: string | null
  placeholder: string
  error?: string
  disabled?: boolean
  onOpen: () => void
}

/** A field whose value is picked on a full-screen search screen: the row shows the choice and opens the picker. */
function PickerField({ id, label, value, placeholder, error, disabled = false, onOpen }: PickerFieldProps) {
  const { token } = theme.useToken()
  const errorId = `${id}-error`
  return (
    <Field label={label} labelId={`${id}-label`} error={error} errorId={errorId}>
      <button
        id={id}
        type="button"
        className="m-list-row"
        aria-label={`${label}: ${value ?? placeholder}`}
        aria-haspopup="dialog"
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? errorId : undefined}
        disabled={disabled}
        onClick={onOpen}
        style={{
          border: `1px solid ${error ? token.colorError : token.colorBorder}`,
          borderRadius: token.borderRadius,
          background: disabled ? token.colorBgContainerDisabled : token.colorBgContainer,
          padding: '10px 12px',
        }}
      >
        <span
          style={{
            flex: 1,
            minWidth: 0,
            overflowWrap: 'anywhere',
            // Secondary, not placeholder grey: the empty text is an instruction («Сначала выберите поставщика»).
            color: value ? token.colorText : token.colorTextSecondary,
          }}
        >
          {value ?? placeholder}
        </span>
        <RightOutlined aria-hidden />
      </button>
    </Field>
  )
}
