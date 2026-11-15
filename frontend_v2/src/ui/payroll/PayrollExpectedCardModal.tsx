import { useEffect, useState } from 'react'
import { Alert, Button, InputNumber, Modal, Skeleton, Space, Table, Typography, message } from 'antd'
import { getPayrollPayoutState, type PayrollPayoutStateDto } from '../../lib/api'
import { updateExpectedCard } from '../../lib/payrollCardApi'
import { fmtMoney } from './payrollFormat'

type Row = {
  employee_id: number
  full_name: string
  accrued: number
  cardPaid: number
  amount: number | null
  /** Amount as loaded; unchanged rows are not sent, so a prefilled value is not marked as set by hand. */
  initialAmount: number
}

/**
 * Expected card amounts of an accrual (draft or accepted). The cash desk keeps this part in reserve until the card
 * payout arrives. Prefilled by the server from last month's card fact; saving marks only the changed values as set
 * by hand (unchanged rows are not sent and keep following last month's fact).
 */
export function PayrollExpectedCardModal({
  open,
  documentId,
  onClose,
  onSaved,
}: {
  open: boolean
  documentId: number
  onClose: () => void
  onSaved: (state: PayrollPayoutStateDto) => void
}) {
  const [rows, setRows] = useState<Row[]>([])
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    let cancelled = false
    setError(null)
    setLoading(true)
    getPayrollPayoutState(documentId)
      .then((s) => {
        if (cancelled) return
        setRows(
          s.employees.map((e) => ({
            employee_id: e.employee_id,
            full_name: e.full_name,
            accrued: Number(e.accrued),
            cardPaid: Number(e.card_paid ?? 0),
            amount: Number(e.card_expected ?? 0),
            initialAmount: Number(e.card_expected ?? 0),
          })),
        )
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Не удалось загрузить сотрудников')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [open, documentId])

  const invalid = rows.some((r) => r.amount === null || r.amount < 0)
  const changed = rows.filter((r) => r.amount !== r.initialAmount)

  const onSubmit = async () => {
    if (invalid) return
    if (changed.length === 0) {
      onClose()
      return
    }
    setSaving(true)
    setError(null)
    try {
      const state = await updateExpectedCard(
        documentId,
        changed.map((r) => ({ employee_id: r.employee_id, amount: (r.amount as number).toFixed(2) })),
      )
      message.success('Ожидаемая карта сохранена')
      onSaved(state)
      onClose()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Не удалось сохранить')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      title="Ожидаемая карта"
      open={open}
      onCancel={onClose}
      width={720}
      destroyOnClose
      footer={[
        <Button key="cancel" onClick={onClose}>
          Отмена
        </Button>,
        <Button
          key="ok"
          type="primary"
          loading={saving}
          disabled={loading || invalid || rows.length === 0}
          onClick={() => void onSubmit()}
        >
          Сохранить
        </Button>,
      ]}
    >
      <Space direction="vertical" style={{ display: 'flex' }} size={12}>
        <Typography.Text type="secondary">
          Сколько каждому сотруднику придёт на карту. Пока карта не пришла, касса не выдаёт эту часть.
        </Typography.Text>
        {error ? <Alert type="error" showIcon message={error} /> : null}
        {loading ? <Skeleton active /> : null}
        {!loading ? (
          <Table<Row>
            rowKey="employee_id"
            size="small"
            pagination={false}
            dataSource={rows}
            scroll={{ x: 'max-content' }}
            locale={{ emptyText: 'В начислении нет сотрудников' }}
            columns={[
              { title: 'Сотрудник', dataIndex: 'full_name' },
              { title: 'Начислено', dataIndex: 'accrued', width: 140, render: (v: number) => fmtMoney(v) },
              { title: 'Пришло на карту', dataIndex: 'cardPaid', width: 150, render: (v: number) => fmtMoney(v) },
              {
                title: 'Ожидается на карту',
                key: 'amount',
                width: 190,
                render: (_, r) => (
                  <InputNumber
                    aria-label={`Ожидается на карту: ${r.full_name}`}
                    min={0}
                    step={1000}
                    style={{ width: '100%' }}
                    value={r.amount}
                    status={r.amount === null ? 'error' : undefined}
                    onChange={(v) =>
                      setRows((prev) =>
                        prev.map((x) => (x.employee_id === r.employee_id ? { ...x, amount: v ?? null } : x)),
                      )
                    }
                  />
                ),
              },
            ]}
          />
        ) : null}
      </Space>
    </Modal>
  )
}
