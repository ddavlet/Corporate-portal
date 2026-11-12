import { Button, Input, InputNumber, Select, Typography, Upload, theme } from 'antd'
import { MobileSheet } from '../MobileSheet'
import { MobileActionsTheme } from './mobileActionsTheme'
import { Field } from './MobileFormFieldWidget'
import type { RequestCreateForm } from './useRequestCreateForm'

const CURRENCIES = ['UZS', 'USD', 'EUR', 'RUB'].map((c) => ({ value: c, label: c }))

export type NewContractSheetProps = {
  form: Pick<
    RequestCreateForm,
    | 'newContractOpen'
    | 'setNewContractOpen'
    | 'newContractSaving'
    | 'saveNewContract'
    | 'ncNumber'
    | 'setNcNumber'
    | 'ncDateFrom'
    | 'setNcDateFrom'
    | 'ncDateTo'
    | 'setNcDateTo'
    | 'ncAmount'
    | 'setNcAmount'
    | 'ncCurrency'
    | 'setNcCurrency'
    | 'ncTerms'
    | 'setNcTerms'
    | 'ncAcc'
    | 'setNcAcc'
    | 'ncFileList'
    | 'setNcFileList'
    | 'fieldErrors'
  >
  /** The request's vendor the contract is made with. */
  vendorLabel: string | null
}

/**
 * «Новый договор» of the phone wizard: a bottom sheet with the fields of the desktop dialog (number, start date and the
 * contract file are required). Saving picks the new contract for the request.
 */
export function NewContractSheet({ form, vendorLabel }: NewContractSheetProps) {
  const { token } = theme.useToken()
  const errors = form.fieldErrors
  const close = () => form.setNewContractOpen(false)

  return (
    <MobileSheet
      open={form.newContractOpen}
      onClose={close}
      title="Новый договор"
      footer={
        <MobileActionsTheme>
          <div style={{ display: 'flex', gap: 8 }}>
            <Button style={{ flex: 1, height: 44 }} onClick={close} disabled={form.newContractSaving}>
              Отмена
            </Button>
            <Button
              type="primary"
              style={{ flex: 1, height: 44 }}
              loading={form.newContractSaving}
              onClick={() => void form.saveNewContract()}
            >
              Сохранить
            </Button>
          </div>
        </MobileActionsTheme>
      }
    >
      <div style={{ display: 'grid', gap: 16 }}>
        <Typography.Text style={{ color: token.colorTextSecondary, overflowWrap: 'anywhere' }}>
          Поставщик: {vendorLabel ?? 'текущий выбор в заявке'}
        </Typography.Text>
        <Field label="Номер договора" htmlFor="new-contract-number" error={errors.contractNumber} errorId="new-contract-number-error">
          <Input
            id="new-contract-number"
            status={errors.contractNumber ? 'error' : undefined}
            aria-invalid={errors.contractNumber ? true : undefined}
            aria-describedby={errors.contractNumber ? 'new-contract-number-error' : undefined}
            value={form.ncNumber}
            onChange={(e) => form.setNcNumber(e.target.value)}
          />
        </Field>
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: 8 }}>
          <Field label="Дата с" htmlFor="new-contract-date-from" error={errors.contractDateFrom} errorId="new-contract-date-from-error">
            <Input
              id="new-contract-date-from"
              type="date"
              status={errors.contractDateFrom ? 'error' : undefined}
              aria-invalid={errors.contractDateFrom ? true : undefined}
              aria-describedby={errors.contractDateFrom ? 'new-contract-date-from-error' : undefined}
              value={form.ncDateFrom}
              onChange={(e) => form.setNcDateFrom(e.target.value)}
            />
          </Field>
          <Field label="Дата по" htmlFor="new-contract-date-to">
            <Input
              id="new-contract-date-to"
              type="date"
              value={form.ncDateTo}
              onChange={(e) => form.setNcDateTo(e.target.value)}
            />
          </Field>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) 112px', gap: 8 }}>
          <Field label="Сумма" htmlFor="new-contract-amount">
            <InputNumber
              id="new-contract-amount"
              style={{ width: '100%' }}
              inputMode="decimal"
              min={0.01}
              step={0.01}
              value={form.ncAmount ?? undefined}
              onChange={(v) => form.setNcAmount(typeof v === 'number' ? v : null)}
            />
          </Field>
          <Field label="Валюта" htmlFor="new-contract-currency">
            <Select
              id="new-contract-currency"
              style={{ width: '100%' }}
              value={form.ncCurrency}
              onChange={form.setNcCurrency}
              options={CURRENCIES}
            />
          </Field>
        </div>
        <Field label="Расчётный счёт" htmlFor="new-contract-account">
          <Input
            id="new-contract-account"
            inputMode="numeric"
            value={form.ncAcc}
            onChange={(e) => form.setNcAcc(e.target.value)}
          />
        </Field>
        <Field label="Условия" htmlFor="new-contract-terms">
          <Input.TextArea
            id="new-contract-terms"
            autoSize={{ minRows: 2, maxRows: 6 }}
            value={form.ncTerms}
            onChange={(e) => form.setNcTerms(e.target.value)}
          />
        </Field>
        <Field label="Файл договора" labelId="new-contract-file-label" error={errors.contractFile} errorId="new-contract-file-error">
          <Upload
            maxCount={1}
            fileList={form.ncFileList}
            beforeUpload={() => false}
            onChange={({ fileList }) => form.setNcFileList(fileList)}
          >
            <Button aria-describedby={errors.contractFile ? 'new-contract-file-error' : 'new-contract-file-label'}>
              Выбрать файл
            </Button>
          </Upload>
        </Field>
      </div>
    </MobileSheet>
  )
}
