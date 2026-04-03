import { useMemo, useState } from 'react'
import { Alert, Button, Card, Input, Typography, message } from 'antd'
import { useSearchParams } from 'react-router-dom'
import { confirmPaymentViaWebApp } from '../../lib/api'
import { resolvePaymentApprovalId } from './tgPaymentApprovalId'

export function TgPaymentConfirmPage() {
  const [searchParams] = useSearchParams()
  const [expenseId, setExpenseId] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const approvalId = useMemo(() => resolvePaymentApprovalId(searchParams), [searchParams])
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

      <div className="tg-sticky-actions">
        <Button type="primary" block onClick={() => void submit()} loading={saving}>
          Подтвердить выплату
        </Button>
      </div>
    </div>
  )
}
