import { useRef, type ReactNode, type Ref } from 'react'
import { useNavigate } from 'react-router-dom'
import { Alert, Button, Input, InputNumber, Select, Typography, theme } from 'antd'
import { CloseOutlined } from '@ant-design/icons'

import { cashRegisterLabel } from '../lib/cashRegisterTransfer'
import { closeToCash } from './cashMobileNav'
import { MobileStateWidget } from './MobileStateWidget'
import { useModuleAccess } from './moduleAccess'
import { MobileActionsTheme, mobileToneTextColor } from './requests/mobileActionsTheme'
import { Field } from './requests/MobileFormFieldWidget'
import { useCashRegisterTransferForm, type CashRegisterTransferField } from './useCashRegisterTransferForm'

const TITLE = 'Перевод между кассами'
const TEST_ID = 'cash-transfer-mobile'

/**
 * `/cash/transfer` on a phone: the desktop «Перевести между кассами» modal (CashRegisterTransferButton) as a
 * full-screen form, with its fields and rules; the request is created by submitCashRegisterTransfer only. After it is
 * sent — a toast and back to «Касса»; when it went to approval without the target register — a warning and back too
 * (another «Отправить» would create a second request); any other error stays on the form with the values kept.
 * Without the «cash» module — «Раздел недоступен», and nothing is requested.
 */
export function CashRegisterTransferMobilePage() {
  const navigate = useNavigate()
  const { loading, hasAccess } = useModuleAccess()
  const close = () => closeToCash(navigate)

  if (!loading && hasAccess('cash')) return <CashRegisterTransferForm onClose={close} />

  return (
    <Screen onClose={close}>
      <div style={{ padding: 16 }}>
        {loading ? (
          <MobileStateWidget state="loading" rows={2} />
        ) : (
          <MobileStateWidget
            state="empty"
            title="Раздел недоступен"
            description="Модуль «Касса» не включён для вашей роли."
            action={<Button onClick={close}>Закрыть</Button>}
          />
        )}
      </div>
    </Screen>
  )
}

/** The full-screen frame: «Закрыть» and the heading on top, the body, an optional bottom bar. */
function Screen({ onClose, bottom, bodyRef, children }: {
  onClose: () => void
  bottom?: ReactNode
  bodyRef?: Ref<HTMLDivElement>
  children: ReactNode
}) {
  const { token } = theme.useToken()
  return (
    <div className="m-fullscreen m-root" data-testid={TEST_ID} style={{ background: token.colorBgLayout }}>
      <header
        className="m-header"
        style={{ position: 'static', background: token.colorBgContainer, borderBottom: `1px solid ${token.colorBorderSecondary}` }}
      >
        <Button type="text" className="m-header__button" icon={<CloseOutlined />} aria-label="Закрыть" onClick={onClose} />
        <h1 className="m-header__title m-ellipsis">{TITLE}</h1>
      </header>
      <div ref={bodyRef} className="m-fullscreen__body">
        {children}
      </div>
      {bottom}
    </div>
  )
}

function CashRegisterTransferForm({ onClose }: { onClose: () => void }) {
  const { token } = theme.useToken()
  const bodyRef = useRef<HTMLDivElement>(null)
  const form = useCashRegisterTransferForm()
  const { values, errors, fromRegister, toRegister } = form

  // A refused submit: bring the first field with an error into view (it renders on the next frame).
  const scrollToFirstError = () => {
    requestAnimationFrame(() => {
      bodyRef.current?.querySelector('[role="alert"]')?.scrollIntoView?.({ block: 'center', behavior: 'smooth' })
    })
  }

  const submit = async () => {
    const result = await form.submit()
    if (result === 'created' || result === 'target_error') onClose()
    else if (result === 'invalid' || result === 'failed') scrollToFirstError()
  }

  const errorProps = (field: CashRegisterTransferField, id: string) =>
    errors[field] ? { status: 'error' as const, 'aria-invalid': true, 'aria-describedby': `${id}-error` } : {}

  if (form.loading) {
    return (
      <Screen onClose={onClose}>
        <div style={{ padding: 16 }}>
          <MobileStateWidget state="loading" rows={2} />
        </div>
      </Screen>
    )
  }

  if (form.loadError) {
    return (
      <Screen onClose={onClose}>
        <div style={{ padding: 16 }}>
          <MobileStateWidget state="error" title="Не удалось загрузить кассы" description={form.loadError} onRetry={form.reload} />
        </div>
      </Screen>
    )
  }

  if (form.registers.length < 2) {
    return (
      <Screen onClose={onClose}>
        <div style={{ padding: 16 }}>
          <MobileStateWidget
            state="empty"
            title="Нет касс для перевода"
            description="Для перевода нужны минимум две активные кассы."
            action={<Button onClick={onClose}>Закрыть</Button>}
          />
        </div>
      </Screen>
    )
  }

  const bottom = (
    <MobileActionsTheme>
      <div
        className="m-bottom-bar"
        style={{ position: 'static', background: token.colorBgContainer, borderTop: `1px solid ${token.colorBorderSecondary}` }}
      >
        <Button
          type="primary"
          block
          style={{ height: 44 }}
          loading={form.submitting}
          disabled={form.submitting}
          onClick={() => void submit()}
        >
          Отправить
        </Button>
      </div>
    </MobileActionsTheme>
  )

  return (
    <Screen onClose={onClose} bottom={bottom} bodyRef={bodyRef}>
      <div style={{ display: 'grid', gap: 16, padding: 16, minWidth: 0 }}>
        {form.submitError ? <Alert type="error" showIcon message={form.submitError} /> : null}
        <Field label="Из кассы" htmlFor="cash-transfer-from" error={errors.fromId} errorId="cash-transfer-from-error">
          <Select<number>
            id="cash-transfer-from"
            style={{ width: '100%' }}
            placeholder="Касса-источник"
            value={values.fromId ?? undefined}
            onChange={(v) => form.setFromId(v ?? null)}
            options={form.fromOptions}
            {...errorProps('fromId', 'cash-transfer-from')}
          />
        </Field>
        <Field label="В кассу" htmlFor="cash-transfer-to" error={errors.toId} errorId="cash-transfer-to-error">
          <Select<number>
            id="cash-transfer-to"
            style={{ width: '100%' }}
            placeholder="Касса-назначение"
            value={values.toId ?? undefined}
            onChange={(v) => form.setToId(v ?? null)}
            options={form.toOptions}
            {...errorProps('toId', 'cash-transfer-to')}
          />
        </Field>
        <Field
          label={fromRegister ? `Сумма (${fromRegister.currency})` : 'Сумма'}
          htmlFor="cash-transfer-amount"
          error={errors.amount}
          errorId="cash-transfer-amount-error"
        >
          <InputNumber
            id="cash-transfer-amount"
            style={{ width: '100%' }}
            min={0.01}
            inputMode="decimal"
            value={values.amount}
            onChange={(v) => form.setAmount(typeof v === 'number' ? v : null)}
            {...errorProps('amount', 'cash-transfer-amount')}
          />
        </Field>
        {form.currencyMismatch && toRegister ? (
          <>
            <Typography.Text data-testid="cash-transfer-currency-warning" style={{ color: mobileToneTextColor('warning', token) }}>
              Кассы в разных валютах: укажите, сколько {toRegister.currency} поступит в кассу-назначение.
            </Typography.Text>
            <Field
              label={`Сумма зачисления (${toRegister.currency})`}
              htmlFor="cash-transfer-to-amount"
              error={errors.toAmount}
              errorId="cash-transfer-to-amount-error"
            >
              <InputNumber
                id="cash-transfer-to-amount"
                style={{ width: '100%' }}
                min={0.01}
                inputMode="decimal"
                value={values.toAmount}
                onChange={(v) => form.setToAmount(typeof v === 'number' ? v : null)}
                {...errorProps('toAmount', 'cash-transfer-to-amount')}
              />
            </Field>
          </>
        ) : null}
        <Field label="Примечание" htmlFor="cash-transfer-note">
          <Input.TextArea
            id="cash-transfer-note"
            autoSize={{ minRows: 2, maxRows: 8 }}
            maxLength={1000}
            value={values.note}
            onChange={(e) => form.setNote(e.target.value)}
          />
        </Field>
        {fromRegister && toRegister ? (
          <Typography.Text style={{ color: token.colorTextSecondary, overflowWrap: 'anywhere', minWidth: 0 }}>
            {cashRegisterLabel(fromRegister)} ({fromRegister.currency}) → {cashRegisterLabel(toRegister)} ({toRegister.currency})
          </Typography.Text>
        ) : null}
      </div>
    </Screen>
  )
}
