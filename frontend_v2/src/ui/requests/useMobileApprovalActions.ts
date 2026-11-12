import { useCallback, useRef, useState } from 'react'
import { message } from 'antd'
import { confirmPaymentViaWebApp, setRequestApprovalDecision, type ApprovalDecision } from '../../lib/api'
import { refreshActionItems } from '../../lib/useActionItems'

export type MobileApprovalActions = {
  busy: boolean
  /** Approves or rejects a step; `comment` (the reason of a rejection) is sent only when it is not blank. */
  decide: (step: number, decision: ApprovalDecision, comment?: string) => Promise<boolean>
  /** Confirms a payment step with the number of the payment document (the same API as the desktop modal). */
  confirmPayment: (approvalId: number, expenseId: string) => Promise<boolean>
}

const CALLBACK_HINT = 'Этот шаг настроен на подтверждение в Telegram — используйте бота.'

/**
 * Decisions and payment confirmation of the phone request card. The desktop page keeps its own handlers (and their
 * error texts); here the errors come from the API helpers. After a success the card and the «requires my action»
 * counter are refreshed at once instead of waiting for the next 60 s poll. Resolves to `true` on success.
 */
export function useMobileApprovalActions(
  requestId: number | null | undefined,
  refreshDetail: () => Promise<void> | void,
): MobileApprovalActions {
  const [busy, setBusy] = useState(false)
  // A second tap while the first request is in flight must not send the decision twice.
  const inFlight = useRef(false)

  const run = useCallback(
    async (action: () => Promise<unknown>, successText: string, onError?: (msg: string) => void): Promise<boolean> => {
      if (inFlight.current) return false
      inFlight.current = true
      setBusy(true)
      try {
        await action()
      } catch (e: unknown) {
        const msg = e instanceof Error && e.message ? e.message : 'Не удалось выполнить действие'
        message.error(msg)
        onError?.(msg)
        inFlight.current = false
        setBusy(false)
        return false
      }
      message.success(successText)
      try {
        await refreshDetail()
      } catch {
        // The decision is already saved: a failed reload of the card must not turn it into a failure (the sheet would
        // stay open and a second tap would hit «step already processed»). The card shows its own reload error.
      } finally {
        void refreshActionItems()
        inFlight.current = false
        setBusy(false)
      }
      return true
    },
    [refreshDetail],
  )

  const decide = useCallback<MobileApprovalActions['decide']>(
    (step, decision, comment) => {
      if (requestId == null) return Promise.resolve(false)
      const trimmed = comment?.trim()
      return run(
        () =>
          setRequestApprovalDecision({
            requestId,
            step,
            decision,
            ...(trimmed ? { comment: trimmed } : {}),
          }),
        decision === 'approved' ? 'Шаг одобрен' : 'Шаг отклонён',
      )
    },
    [requestId, run],
  )

  const confirmPayment = useCallback<MobileApprovalActions['confirmPayment']>(
    (approvalId, expenseId) =>
      run(
        () => confirmPaymentViaWebApp({ approval_id: approvalId, expense_id: expenseId.trim() }),
        'Выплата подтверждена',
        (msg) => {
          if (/callback/i.test(msg)) message.info(CALLBACK_HINT)
        },
      ),
    [run],
  )

  return { busy, decide, confirmPayment }
}
