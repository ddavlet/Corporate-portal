import { useEffect, useState } from 'react'
import { Alert, Button, Descriptions, Modal, Space, Typography, message } from 'antd'
import dayjs from 'dayjs'
import { listEmployees, type EmployeeDto } from '../../lib/api'
import { assignCardPayout, linkBankEmployee, type PayrollCardUnlinkedDto } from '../../lib/payrollCardApi'
import { EmployeeSelect } from './EmployeeSelect'
import { fmtMoney } from './payrollFormat'

/** link: every payout of this bank employee goes to the portal employee; assign: only this one payout. */
export type BankEmployeeLinkMode = 'link' | 'assign'

export function bankEmployeeLinkMode(row: PayrollCardUnlinkedDto): BankEmployeeLinkMode {
  return row.bank_employee_id !== null ? 'link' : 'assign'
}

export function BankEmployeeLinkModal({
  row,
  onClose,
  onDone,
}: {
  /** The payout to resolve; null keeps the modal closed. */
  row: PayrollCardUnlinkedDto | null
  onClose: () => void
  onDone: () => void
}) {
  const open = row !== null
  const mode = row ? bankEmployeeLinkMode(row) : 'link'
  const [employees, setEmployees] = useState<EmployeeDto[]>([])
  const [employeeId, setEmployeeId] = useState<number | undefined>()
  const [employeesLoading, setEmployeesLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!row) return
    let cancelled = false
    setError(null)
    // The candidate is an option right away, so the select shows the name, not the bare id, while the list loads.
    setEmployees(row.candidate ? [row.candidate] : [])
    setEmployeeId(row.candidate?.id)
    setEmployeesLoading(true)
    listEmployees()
      .then((list) => {
        if (cancelled) return
        // The candidate is always selectable, even if the list came back without it.
        const candidate = row.candidate
        setEmployees(candidate && !list.some((e) => e.id === candidate.id) ? [candidate, ...list] : list)
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Не удалось загрузить сотрудников')
      })
      .finally(() => {
        if (!cancelled) setEmployeesLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [row])

  const onSubmit = async () => {
    if (!row || employeeId === undefined) return
    setSaving(true)
    setError(null)
    try {
      if (mode === 'link' && row.bank_employee_id !== null) {
        await linkBankEmployee({ bank_employee_id: row.bank_employee_id, employee_id: employeeId })
        message.success('Сотрудник банка привязан')
      } else {
        await assignCardPayout(row.payout_id, employeeId)
        message.success('Выплата отнесена к сотруднику')
      }
      onDone()
      onClose()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Не удалось сохранить')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      title={mode === 'link' ? 'Привязать сотрудника банка' : 'Отнести выплату к сотруднику'}
      open={open}
      onCancel={onClose}
      destroyOnClose
      footer={[
        <Button key="cancel" onClick={onClose}>
          Отмена
        </Button>,
        <Button
          key="ok"
          type="primary"
          loading={saving}
          disabled={employeeId === undefined}
          onClick={() => void onSubmit()}
        >
          {mode === 'link' ? 'Привязать' : 'Отнести'}
        </Button>,
      ]}
    >
      {row ? (
        <Space direction="vertical" style={{ display: 'flex' }} size={12}>
          <Descriptions bordered size="small" column={1}>
            <Descriptions.Item label="В банке">{row.bank_full_name || row.name_from_purpose || '—'}</Descriptions.Item>
            <Descriptions.Item label="Карта">{row.masked_card || row.card_account_masked}</Descriptions.Item>
            <Descriptions.Item label="Сумма">
              {fmtMoney(row.amount)} · {dayjs(row.paid_on).format('DD.MM.YYYY')}
            </Descriptions.Item>
          </Descriptions>
          <Typography.Text type="secondary">
            {mode === 'link'
              ? 'Все выплаты этого сотрудника банка, прошлые и будущие, будут относиться к выбранному сотруднику.'
              : 'У выплаты нет кода сотрудника банка. Будет отнесена только эта выплата; следующие придётся относить так же.'}
          </Typography.Text>
          <div>
            <label htmlFor="bank-employee-link-employee" style={{ display: 'block', marginBottom: 4 }}>
              Сотрудник в портале
            </label>
            <EmployeeSelect
              id="bank-employee-link-employee"
              loading={employeesLoading}
              value={employeeId}
              onChange={setEmployeeId}
              employees={employees}
              onEmployeeCreated={(created) => setEmployees((prev) => [created, ...prev])}
            />
            {row.candidate && employeeId === row.candidate.id ? (
              <Typography.Text type="secondary" style={{ display: 'block', marginTop: 4, fontSize: 12 }}>
                Предложен по совпадению ФИО — проверьте перед сохранением.
              </Typography.Text>
            ) : null}
          </div>
          {error ? <Alert type="error" showIcon message={error} /> : null}
        </Space>
      ) : null}
    </Modal>
  )
}
