import { useEffect, useMemo, useState } from 'react'
import { Alert, Button, DatePicker, InputNumber, Modal, Select, Skeleton, Space, Table, Typography, message } from 'antd'
import { DeleteOutlined } from '@ant-design/icons'
import dayjs, { type Dayjs } from 'dayjs'
import {
  createPayrollPayout,
  getCashRegisters,
  getPayrollPayoutState,
  listPayablePayrollDocuments,
  type CashRegisterDto,
  type PayablePayrollDocumentDto,
  type PayrollPayoutStateDto,
} from '../../lib/api'

type Row = { employee_id: number; full_name: string; remaining: number; amount: number | null }

const fmt = (n: number) => n.toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

export function PayrollPayoutModal({
  open,
  onClose,
  onDone,
  documentId,
}: {
  open: boolean
  onClose: () => void
  onDone: (cashExpenseId: number) => void
  documentId?: number
}) {
  const [selectedDoc, setSelectedDoc] = useState<number | undefined>(documentId)
  const [payable, setPayable] = useState<PayablePayrollDocumentDto[]>([])
  const [state, setState] = useState<PayrollPayoutStateDto | null>(null)
  const [rows, setRows] = useState<Row[]>([])
  const [registers, setRegisters] = useState<CashRegisterDto[]>([])
  const [walletId, setWalletId] = useState<number | undefined>()
  const [date, setDate] = useState<Dayjs>(dayjs())
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showValidation, setShowValidation] = useState(false)

  useEffect(() => {
    if (!open) return
    let cancelled = false
    setSelectedDoc(documentId)
    setError(null)
    getCashRegisters()
      .then((list) => {
        if (cancelled) return
        const uzs = list.filter((r) => r.is_active && r.currency === 'UZS')
        setRegisters(uzs)
        setWalletId((uzs.find((r) => r.is_default_for_currency) ?? uzs[0])?.wallet_id)
      })
      .catch((e: unknown) => !cancelled && setError(e instanceof Error ? e.message : 'Не удалось загрузить кассы'))
    if (documentId === undefined) {
      listPayablePayrollDocuments()
        .then((list) => !cancelled && setPayable(list))
        .catch((e: unknown) => !cancelled && setError(e instanceof Error ? e.message : 'Не удалось загрузить начисления'))
    }
    return () => {
      cancelled = true
    }
  }, [open, documentId])

  useEffect(() => {
    setError(null)
    setShowValidation(false)
    if (!open || selectedDoc === undefined) {
      setState(null)
      setRows([])
      return
    }
    let cancelled = false
    setLoading(true)
    getPayrollPayoutState(selectedDoc)
      .then((s) => {
        if (cancelled) return
        setState(s)
        setRows(
          s.employees
            .filter((e) => Number(e.remaining) > 0)
            .map((e) => ({
              employee_id: e.employee_id,
              full_name: e.full_name,
              remaining: Number(e.remaining),
              amount: Number(e.remaining),
            })),
        )
      })
      .catch((e: unknown) => !cancelled && setError(e instanceof Error ? e.message : 'Ошибка загрузки'))
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [open, selectedDoc])

  const total = useMemo(() => rows.reduce((acc, r) => acc + (r.amount ?? 0), 0), [rows])

  const validationError = useMemo(() => {
    if (rows.length === 0) return 'Нет сотрудников для выплаты'
    for (const r of rows) {
      if (!r.amount || r.amount <= 0) return `${r.full_name}: сумма должна быть больше нуля`
      if (r.amount > r.remaining) return `${r.full_name}: можно выплатить не более ${fmt(r.remaining)}`
    }
    if (!walletId) return 'Выберите кассу'
    return null
  }, [rows, walletId])

  const onSubmit = async () => {
    setShowValidation(true)
    if (validationError || selectedDoc === undefined || !walletId) return
    setSaving(true)
    try {
      const res = await createPayrollPayout(selectedDoc, {
        wallet_id: walletId,
        date: date.format('YYYY-MM-DD'),
        items: rows.map((r) => ({ employee_id: r.employee_id, amount: (r.amount as number).toFixed(2) })),
      })
      message.success('Расход создан')
      onDone(res.cash_expense_id)
      onClose()
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : 'Ошибка создания расхода')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      title="Выплата ЗП из кассы"
      open={open}
      onCancel={onClose}
      width={760}
      destroyOnClose
      footer={[
        <Button key="cancel" onClick={onClose}>
          Отмена
        </Button>,
        <Button
          key="ok"
          type="primary"
          loading={saving}
          disabled={!state?.can_pay}
          onClick={() => void onSubmit()}
        >
          Создать расход
        </Button>,
      ]}
    >
      <Space direction="vertical" style={{ display: 'flex' }} size={12}>
        {error ? <Alert type="error" showIcon message={error} /> : null}
        {documentId === undefined ? (
          <Select
            placeholder="Начисление"
            style={{ width: '100%' }}
            value={selectedDoc}
            onChange={setSelectedDoc}
            options={payable.map((d) => ({
              value: d.id,
              label: `${d.label}${d.period_month ? ` · ${dayjs(d.period_month).format('MM.YYYY')}` : ''} · остаток ${fmt(Number(d.remaining_total))}`,
            }))}
            notFoundContent="Нет начислений к выплате"
          />
        ) : null}
        <Space wrap>
          <Select
            placeholder="Касса"
            style={{ width: 240 }}
            value={walletId}
            onChange={setWalletId}
            options={registers.map((r) => ({ value: r.wallet_id, label: r.name }))}
          />
          <DatePicker value={date} onChange={(d) => d && setDate(d)} format="DD.MM.YYYY" allowClear={false} />
        </Space>
        {loading ? <Skeleton active /> : null}
        {state && !state.can_pay ? <Alert type="warning" showIcon message={state.reason} /> : null}
        {state?.can_pay ? (
          <Table<Row>
            rowKey="employee_id"
            size="small"
            pagination={false}
            dataSource={rows}
            columns={[
              { title: 'Сотрудник', dataIndex: 'full_name' },
              { title: 'Остаток', dataIndex: 'remaining', width: 140, render: (v: number) => fmt(v) },
              {
                title: 'К выплате',
                key: 'amount',
                width: 180,
                render: (_, r) => (
                  <InputNumber
                    aria-label={`Сумма: ${r.full_name}`}
                    min={0}
                    value={r.amount}
                    onChange={(v) =>
                      setRows((prev) =>
                        prev.map((x) => (x.employee_id === r.employee_id ? { ...x, amount: v ?? null } : x)),
                      )
                    }
                    style={{ width: '100%' }}
                  />
                ),
              },
              {
                key: 'remove',
                width: 48,
                render: (_, r) => (
                  <Button
                    aria-label={`Убрать ${r.full_name}`}
                    icon={<DeleteOutlined />}
                    onClick={() => setRows((prev) => prev.filter((x) => x.employee_id !== r.employee_id))}
                  />
                ),
              },
            ]}
          />
        ) : null}
        {showValidation && validationError ? <Alert type="error" showIcon message={validationError} /> : null}
        <Typography.Text strong>Итого расход: {fmt(total)}</Typography.Text>
      </Space>
    </Modal>
  )
}
