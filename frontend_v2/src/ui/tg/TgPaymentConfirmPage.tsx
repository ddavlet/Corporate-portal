import { useEffect, useState } from 'react'
import { Alert, Card, Input, Typography, message } from 'antd'
import { useSearchParams } from 'react-router-dom'
import { confirmPaymentViaWebApp } from '../../lib/api'
import { resolvePaymentApprovalId } from './tgPaymentApprovalId'
import { useTgMainButton } from './useTgMainButton'

export function TgPaymentConfirmPage() {
  const [searchParams] = useSearchParams()
  const [expenseId, setExpenseId] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [approvalId, setApprovalId] = useState(0)

  // Do not useMemo only on searchParams: start_param lives in Telegram.WebApp (initData /
  // initDataUnsafe) and can appear after the first paint. Re-read after ready + next frames.
  useEffect(() => {
    let alive = true
    const sync = () => {
      if (!alive) return
      const next = resolvePaymentApprovalId(searchParams)
      setApprovalId((prev) => (prev !== next ? next : prev))
    }
    sync()
    window.Telegram?.WebApp?.ready?.()
    const raf = requestAnimationFrame(sync)
    const t0 = window.setTimeout(sync, 0)
    const t1 = window.setTimeout(sync, 50)
    const t2 = window.setTimeout(sync, 250)
    return () => {
      alive = false
      cancelAnimationFrame(raf)
      window.clearTimeout(t0)
      window.clearTimeout(t1)
      window.clearTimeout(t2)
    }
  }, [searchParams])

  const isApprovalValid = Number.isInteger(approvalId) && approvalId > 0

  const submit = async () => {
    const trimmed = expenseId.trim()
    if (!isApprovalValid) {
      setError(
        'Не найден approval_id: укажите ?approval_id= в URL кнопки или откройте приложение с startapp (start_param / tgWebAppStartParam).',
      )
      return
    }
    if (!trimmed) {
      setError('Введите номер платежа.')
      return
    }
    setSaving(true)
    setError(null)
    try {
      await confirmPaymentViaWebApp({ approval_id: approvalId, expense_id: trimmed })
      message.success('Выплата подтверждена')
      window.Telegram?.WebApp?.close?.()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Ошибка подтверждения выплаты')
    } finally {
      setSaving(false)
    }
  }

  useTgMainButton({
    text: 'Подтвердить выплату',
    onClick: () => void submit(),
    loading: saving,
    disabled: !isApprovalValid,
  })

  return (
    <div className="tg-create-page">
      <Card className="tg-create-card" bordered>
        <Typography.Title level={4}>Подтверждение выплаты</Typography.Title>
        <Typography.Paragraph type="secondary">Введите номер платежа для привязки к заявке.</Typography.Paragraph>

        {error ? <Alert type="error" showIcon message={error} style={{ marginBottom: 12 }} /> : null}

        <Typography.Text strong>Введите номер платежа</Typography.Text>
        <div style={{ height: 8 }} />
        <Input value={expenseId} onChange={(e) => setExpenseId(e.target.value)} placeholder="Например, INV-2026-001" />
      </Card>
    </div>
  )
}
