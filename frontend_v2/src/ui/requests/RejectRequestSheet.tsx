import { useState } from 'react'
import { Button, Input, Typography, theme } from 'antd'
import { MobileSheet } from '../MobileSheet'
import { MobileActionsTheme } from './mobileActionsTheme'
import { RequestSheetSummaryWidget, type RequestSheetSummary } from './RequestSheetSummaryWidget'

const REASON_MAX_LENGTH = 1000

export type RejectRequestSheetProps = {
  open: boolean
  onClose: () => void
  /** Step being rejected, shown in the title. */
  step: number | null
  summary: RequestSheetSummary | null
  busy: boolean
  /** Rejects the step; the reason is passed only when it was typed. Resolves to true on success (the sheet closes). */
  onReject: (comment?: string) => Promise<boolean>
}

/**
 * Rejection of the user's approval step with an optional reason, which the backend stores as the decision comment.
 * A summary of the request on top; «Отмена» and «Отклонить» are pinned in the sheet's footer.
 */
export function RejectRequestSheet({ open, onClose, step, summary, busy, onReject }: RejectRequestSheetProps) {
  const { token } = theme.useToken()
  const [reason, setReason] = useState('')
  // A reopened sheet starts with an empty reason.
  const [wasOpen, setWasOpen] = useState(open)
  if (open !== wasOpen) {
    setWasOpen(open)
    if (open) setReason('')
  }

  const submit = async () => {
    const trimmed = reason.trim()
    const ok = await onReject(trimmed ? trimmed : undefined)
    if (ok) onClose()
  }

  return (
    <MobileSheet
      open={open}
      onClose={onClose}
      title={step != null ? `Отклонить шаг ${step}` : 'Отклонить заявку'}
      footer={
        <MobileActionsTheme>
          <div style={{ display: 'flex', gap: 8 }}>
            <Button style={{ flex: 1, height: 44 }} onClick={onClose} disabled={busy}>
              Отмена
            </Button>
            <Button type="primary" danger style={{ flex: 1, height: 44 }} loading={busy} onClick={() => void submit()}>
              Отклонить
            </Button>
          </div>
        </MobileActionsTheme>
      }
    >
      <div style={{ display: 'grid', gap: 12 }}>
        {summary ? <RequestSheetSummaryWidget summary={summary} testId="reject-request-summary" /> : null}
        <label htmlFor="reject-request-reason" style={{ display: 'grid', gap: 6 }}>
          <Typography.Text strong>Причина</Typography.Text>
          <Typography.Text style={{ color: token.colorTextSecondary }}>
            Необязательно. Причину увидят заявитель и другие согласующие.
          </Typography.Text>
        </label>
        <Input.TextArea
          id="reject-request-reason"
          rows={4}
          value={reason}
          maxLength={REASON_MAX_LENGTH}
          onChange={(e) => setReason(e.target.value)}
          placeholder="Например: нет договора"
        />
      </div>
    </MobileSheet>
  )
}
