import { useState } from 'react'
import { Button, Form, Input, theme } from 'antd'
import { MobileSheet } from '../MobileSheet'
import { MobileActionsTheme, mobileToneTextColor } from './mobileActionsTheme'
import { RequestSheetSummaryWidget, type RequestSheetSummary } from './RequestSheetSummaryWidget'

export type PaymentConfirmSheetProps = {
  open: boolean
  onClose: () => void
  summary: RequestSheetSummary | null
  /** Number already known for the request (`expense_id`), offered as the starting value. */
  initialExpenseId?: string | null
  busy: boolean
  /** Confirms the payment step with the document number; resolves to true on success (the sheet closes). */
  onConfirm: (expenseId: string) => Promise<boolean>
}

const FIELD_ID = 'payment-confirm-expense-id'
const ERROR_ID = 'payment-confirm-expense-id-error'

/**
 * Payment step on the phone: a summary of the request and the required number of the payment document; «Отмена» and
 * «Подтвердить» are pinned in the sheet's footer.
 */
export function PaymentConfirmSheet({ open, onClose, summary, initialExpenseId, busy, onConfirm }: PaymentConfirmSheetProps) {
  const { token } = theme.useToken()
  const [expenseId, setExpenseId] = useState(() => (initialExpenseId ?? '').trim())
  const [error, setError] = useState<string | null>(null)
  // A reopened sheet starts again from the known number and without the old error.
  const [wasOpen, setWasOpen] = useState(open)
  if (open !== wasOpen) {
    setWasOpen(open)
    if (open) {
      setExpenseId((initialExpenseId ?? '').trim())
      setError(null)
    }
  }

  const submit = async () => {
    const value = expenseId.trim()
    if (!value) {
      setError('Введите номер платёжного документа')
      return
    }
    const ok = await onConfirm(value)
    if (ok) onClose()
  }

  return (
    <MobileSheet
      open={open}
      onClose={onClose}
      title="Подтверждение выплаты"
      footer={
        <MobileActionsTheme>
          <div style={{ display: 'flex', gap: 8 }}>
            <Button style={{ flex: 1, height: 44 }} onClick={onClose} disabled={busy}>
              Отмена
            </Button>
            <Button type="primary" style={{ flex: 1, height: 44 }} loading={busy} onClick={() => void submit()}>
              Подтвердить
            </Button>
          </div>
        </MobileActionsTheme>
      }
    >
      <div style={{ display: 'grid', gap: 12 }}>
        {summary ? <RequestSheetSummaryWidget summary={summary} testId="payment-confirm-summary" /> : null}
        {/* No <form> element: Enter in the field must not submit twice (implicit submission and onPressEnter). */}
        <Form layout="vertical" component={false} requiredMark={false}>
          <Form.Item
            label="Номер платёжного документа"
            htmlFor={FIELD_ID}
            validateStatus={error ? 'error' : undefined}
            // Dark red (red 7, ~5.6:1 on white): the default #ff4d4f is about 3.3:1. Without `name` the Form.Item gives
            // the help no id, so the span carries its own id for aria-describedby and announces itself.
            help={
              error ? (
                <span id={ERROR_ID} role="alert" style={{ color: mobileToneTextColor('error', token) }}>
                  {error}
                </span>
              ) : undefined
            }
            style={{ marginBottom: 0 }}
          >
            <Input
              id={FIELD_ID}
              value={expenseId}
              inputMode="numeric"
              autoComplete="off"
              aria-required
              aria-invalid={error ? true : undefined}
              aria-describedby={error ? ERROR_ID : undefined}
              onChange={(e) => {
                setExpenseId(e.target.value)
                if (error) setError(null)
              }}
              onPressEnter={(e) => {
                e.preventDefault()
                void submit()
              }}
            />
          </Form.Item>
        </Form>
      </div>
    </MobileSheet>
  )
}
