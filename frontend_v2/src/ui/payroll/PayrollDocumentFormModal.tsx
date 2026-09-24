import { useEffect, useState } from 'react'
import { Button, DatePicker, Form, InputNumber, Modal, Select, Space, Typography, message } from 'antd'
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons'
import dayjs, { type Dayjs } from 'dayjs'
import {
  PAYROLL_KIND_LABELS,
  createPayrollDraft,
  updatePayrollDraft,
  type PayrollDocumentDetailDto,
  type PayrollKind,
} from '../../lib/api'
import { EmployeeSelect } from './EmployeeSelect'

type FormValues = {
  period_month: Dayjs
  kind: PayrollKind
  lines: { employee_id?: number; sum?: number }[]
}

export function PayrollDocumentFormModal({
  open,
  onClose,
  onSaved,
  initial,
}: {
  open: boolean
  onClose: () => void
  onSaved: (doc: PayrollDocumentDetailDto) => void
  initial?: PayrollDocumentDetailDto
}) {
  const [form] = Form.useForm<FormValues>()
  const [saving, setSaving] = useState(false)
  const lines = Form.useWatch('lines', form) ?? []
  const total = lines.reduce((acc, l) => acc + (Number(l?.sum) || 0), 0)
  const chosenIds = lines.map((l) => l?.employee_id).filter((v): v is number => typeof v === 'number')

  useEffect(() => {
    if (!open) return
    form.setFieldsValue({
      period_month: initial?.period_month ? dayjs(initial.period_month) : dayjs().startOf('month'),
      kind: initial?.kind ?? 'salary',
      lines: initial
        ? initial.lines
            .filter((l) => l.employee_id !== null)
            .map((l) => ({ employee_id: l.employee_id as number, sum: Number(l.sum) }))
        : [{}],
    })
  }, [open, initial, form])

  const onSubmit = async () => {
    try {
      const v = await form.validateFields()
      setSaving(true)
      const payload = {
        period_month: v.period_month.startOf('month').format('YYYY-MM-DD'),
        kind: v.kind,
        lines: v.lines.map((l) => ({ employee_id: l.employee_id as number, sum: String(l.sum) })),
      }
      const doc = initial ? await updatePayrollDraft(initial.id, payload) : await createPayrollDraft(payload)
      message.success(initial ? 'Черновик сохранён' : 'Черновик создан')
      onSaved(doc)
      onClose()
    } catch (e: unknown) {
      if (e && typeof e === 'object' && 'errorFields' in e) return
      message.error(e instanceof Error ? e.message : 'Ошибка сохранения')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      title={initial ? `Черновик начисления ${initial.label}` : 'Новое начисление'}
      open={open}
      onCancel={onClose}
      onOk={() => void onSubmit()}
      confirmLoading={saving}
      okText="Сохранить черновик"
      width={720}
      destroyOnClose
    >
      <Form form={form} layout="vertical">
        <Space wrap>
          <Form.Item name="period_month" label="Период" rules={[{ required: true, message: 'Укажите период' }]}>
            <DatePicker picker="month" format="MM.YYYY" />
          </Form.Item>
          <Form.Item name="kind" label="Тип" rules={[{ required: true }]}>
            <Select
              style={{ width: 160 }}
              options={Object.entries(PAYROLL_KIND_LABELS).map(([value, label]) => ({ value, label }))}
            />
          </Form.Item>
        </Space>
        <Form.List
          name="lines"
          rules={[
            {
              validator: async (_, value) => {
                if (!value || value.length === 0) throw new Error('Добавьте хотя бы одного сотрудника')
              },
            },
          ]}
        >
          {(fields, { add, remove }, { errors }) => (
            <Space direction="vertical" style={{ display: 'flex' }}>
              {fields.map((field) => (
                <Space key={field.key} align="baseline">
                  <Form.Item
                    name={[field.name, 'employee_id']}
                    rules={[{ required: true, message: 'Выберите сотрудника' }]}
                  >
                    <EmployeeSelect
                      excludeIds={chosenIds.filter((id) => id !== lines[field.name]?.employee_id)}
                    />
                  </Form.Item>
                  <Form.Item
                    name={[field.name, 'sum']}
                    rules={[{ required: true, message: 'Сумма' }, { type: 'number', min: 0.01, message: 'Больше нуля' }]}
                  >
                    <InputNumber placeholder="Сумма" min={0} style={{ width: 160 }} />
                  </Form.Item>
                  {fields.length > 1 ? (
                    <Button
                      aria-label="Убрать сотрудника"
                      icon={<DeleteOutlined />}
                      onClick={() => remove(field.name)}
                    />
                  ) : null}
                </Space>
              ))}
              <Button type="dashed" icon={<PlusOutlined />} onClick={() => add({})}>
                Добавить сотрудника в список
              </Button>
              <Form.ErrorList errors={errors} />
              <Typography.Text strong>
                Итого: {total.toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </Typography.Text>
            </Space>
          )}
        </Form.List>
      </Form>
    </Modal>
  )
}
