import { Button, Input, Typography, theme } from 'antd'
import { vendorKindForPaymentType } from '../../lib/requestPaymentTypes'
import { MobileSheet } from '../MobileSheet'
import { MobileActionsTheme } from './mobileActionsTheme'
import { Field } from './MobileFormFieldWidget'
import type { RequestCreateForm } from './useRequestCreateForm'

export type NewVendorSheetProps = {
  form: Pick<
    RequestCreateForm,
    | 'paymentType'
    | 'newVendorOpen'
    | 'setNewVendorOpen'
    | 'newVendorName'
    | 'setNewVendorName'
    | 'newVendorInn'
    | 'setNewVendorInn'
    | 'newVendorAccount'
    | 'setNewVendorAccount'
    | 'newVendorSaving'
    | 'saveNewVendor'
    | 'fieldErrors'
  >
}

/**
 * «Новый поставщик» of the phone wizard: a bottom sheet over the form with the fields of the desktop dialog. The kind
 * (cash or transfer) follows the chosen payment type; a transfer vendor needs an INN. Saving picks the new vendor.
 */
export function NewVendorSheet({ form }: NewVendorSheetProps) {
  const { token } = theme.useToken()
  const isCash = vendorKindForPaymentType(form.paymentType ?? '') === 'cash'
  const errors = form.fieldErrors
  const close = () => form.setNewVendorOpen(false)

  return (
    <MobileSheet
      open={form.newVendorOpen}
      onClose={close}
      title="Новый поставщик"
      footer={
        <MobileActionsTheme>
          <div style={{ display: 'flex', gap: 8 }}>
            <Button style={{ flex: 1, height: 44 }} onClick={close} disabled={form.newVendorSaving}>
              Отмена
            </Button>
            <Button
              type="primary"
              style={{ flex: 1, height: 44 }}
              loading={form.newVendorSaving}
              onClick={() => void form.saveNewVendor()}
            >
              Сохранить
            </Button>
          </div>
        </MobileActionsTheme>
      }
    >
      <div style={{ display: 'grid', gap: 16 }}>
        <Typography.Text style={{ color: token.colorTextSecondary }}>
          Тип: {isCash ? 'наличные' : 'перечисление'} (по выбранному типу оплаты заявки).
        </Typography.Text>
        <Field label="Наименование" htmlFor="new-vendor-name" error={errors.newVendorName} errorId="new-vendor-name-error">
          <Input
            id="new-vendor-name"
            autoComplete="organization"
            status={errors.newVendorName ? 'error' : undefined}
            aria-invalid={errors.newVendorName ? true : undefined}
            aria-describedby={errors.newVendorName ? 'new-vendor-name-error' : undefined}
            value={form.newVendorName}
            onChange={(e) => form.setNewVendorName(e.target.value)}
          />
        </Field>
        {!isCash ? (
          <Field label="ИНН" htmlFor="new-vendor-inn" error={errors.newVendorInn} errorId="new-vendor-inn-error">
            <Input
              id="new-vendor-inn"
              inputMode="numeric"
              status={errors.newVendorInn ? 'error' : undefined}
              aria-invalid={errors.newVendorInn ? true : undefined}
              aria-describedby={errors.newVendorInn ? 'new-vendor-inn-error' : undefined}
              value={form.newVendorInn}
              onChange={(e) => form.setNewVendorInn(e.target.value)}
            />
          </Field>
        ) : null}
        <Field label="Расчётный счёт (необязательно)" htmlFor="new-vendor-account">
          <Input
            id="new-vendor-account"
            inputMode="numeric"
            value={form.newVendorAccount}
            onChange={(e) => form.setNewVendorAccount(e.target.value)}
          />
        </Field>
      </div>
    </MobileSheet>
  )
}
