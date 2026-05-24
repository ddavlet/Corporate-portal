import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Drawer,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  Upload,
  message,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import type { UploadFile } from 'antd/es/upload/interface'
import {
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
  DownloadOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import 'dayjs/locale/ru'
import { useSearchParams } from 'react-router-dom'
import { RequestReturnBackButton } from './requests/RequestReturnBackButton'
import {
  createContract,
  deleteContract,
  fetchContractFile,
  getRequestFormConfig,
  listContracts,
  patchContractJson,
  updateContract,
  type ContractRow,
  type RequestFormConfigCandidateVendor,
} from '../lib/api'

dayjs.locale('ru')

const STATUS_OPTS = [
  { value: 'accepted', label: 'Принят' },
  { value: 'refused', label: 'Отказан' },
]

const DISPLAY_LABELS: Record<string, string> = {
  accepted: 'Активен',
  refused: 'Отказан',
  expired: 'Просрочен',
}

export function ContractsPage() {
  const [searchParams] = useSearchParams()
  const vendorFilter = searchParams.get('vendor')
  const contractFilter = searchParams.get('contract')
  const [rows, setRows] = useState<ContractRow[]>([])
  const [vendors, setVendors] = useState<RequestFormConfigCandidateVendor[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [drawerOpen, setDrawerOpen] = useState(false)
  const [editing, setEditing] = useState<ContractRow | null>(null)
  const [formLoading, setFormLoading] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [form] = Form.useForm()
  const [uploadFiles, setUploadFiles] = useState<UploadFile[]>([])

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    listContracts({})
      .then(setRows)
      .catch((e: unknown) => setError(String(e)))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    getRequestFormConfig()
      .then((cfg) => setVendors(cfg.vendor_candidates ?? []))
      .catch(() => setVendors([]))
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const filteredRows = useMemo(() => {
    if (!vendorFilter) return rows
    const vendorId = Number(vendorFilter)
    if (!Number.isFinite(vendorId)) return rows
    return rows.filter((row) => row.vendor === vendorId)
  }, [rows, vendorFilter])

  const vendorLabel = useMemo(() => {
    const m = new Map<number, string>()
    for (const v of vendors) {
      m.set(v.id, v.name)
    }
    return m
  }, [vendors])

  const openCreate = () => {
    setEditing(null)
    setFormError(null)
    form.resetFields()
    form.setFieldsValue({
      currency: 'UZS',
      contract_status: 'accepted',
      contract_terms: '',
      acc_number: '',
    })
    setUploadFiles([])
    setDrawerOpen(true)
  }

  const openEdit = (r: ContractRow) => {
    setEditing(r)
    setFormError(null)
    form.setFieldsValue({
      vendor: r.vendor,
      contract_number: r.contract_number,
      date_from: r.date_from,
      date_to: r.date_to ?? undefined,
      contract_amount: r.contract_amount != null ? parseFloat(r.contract_amount) : undefined,
      currency: r.currency,
      contract_status: r.contract_status,
      contract_terms: r.contract_terms,
      acc_number: r.acc_number,
    })
    setUploadFiles([])
    setDrawerOpen(true)
  }

  useEffect(() => {
    if (!contractFilter || loading || rows.length === 0) return
    const contractId = Number(contractFilter)
    if (!Number.isFinite(contractId)) return
    const row = rows.find((r) => r.id === contractId)
    if (row) openEdit(row)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- open drawer when deep-linked
  }, [contractFilter, loading, rows])

  const handleDownload = async (r: ContractRow) => {
    try {
      const blob = await fetchContractFile(r.id)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${r.contract_number || 'contract'}-file`
      a.click()
      URL.revokeObjectURL(url)
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : 'Не удалось скачать файл')
    }
  }

  const saveDrawer = async () => {
    let values: Record<string, unknown>
    try {
      values = await form.validateFields()
    } catch {
      return
    }
    const file = uploadFiles[0]?.originFileObj as File | undefined
    if (!editing && !file) {
      setFormError('Прикрепите файл договора.')
      return
    }
    setFormLoading(true)
    setFormError(null)
    try {
      const vendor = Number(values.vendor)
      const common = {
        vendor,
        contract_number: String(values.contract_number || '').trim(),
        date_from: String(values.date_from || ''),
        date_to: values.date_to ? String(values.date_to) : null,
        contract_amount: values.contract_amount != null ? String(values.contract_amount) : null,
        currency: String(values.currency || 'UZS'),
        contract_status: String(values.contract_status || 'accepted'),
        contract_terms: String(values.contract_terms || ''),
        acc_number: String(values.acc_number || ''),
      }
      if (editing) {
        await patchContractJson(editing.id, common)
        if (file) await updateContract(editing.id, { contract_file: file })
      } else {
        await createContract({ ...common, contract_file: file ?? undefined })
      }
      message.success(editing ? 'Сохранено' : 'Договор создан')
      setDrawerOpen(false)
      load()
    } catch (e: unknown) {
      setFormError(String(e))
    } finally {
      setFormLoading(false)
    }
  }

  const handleDelete = (r: ContractRow) => {
    Modal.confirm({
      title: `Удалить договор «${r.contract_number}»?`,
      okText: 'Удалить',
      okButtonProps: { danger: true },
      cancelText: 'Отмена',
      onOk: async () => {
        try {
          await deleteContract(r.id)
          message.success('Удалено')
          load()
        } catch (e: unknown) {
          message.error(String(e))
        }
      },
    })
  }

  const columns: ColumnsType<ContractRow> = [
    {
      title: 'Номер',
      dataIndex: 'contract_number',
      key: 'contract_number',
      render: (t: string, r) => (
        <Space direction="vertical" size={0}>
          <Typography.Text strong>{t}</Typography.Text>
          <Typography.Text type="secondary">{vendorLabel.get(r.vendor) ?? `#${r.vendor}`}</Typography.Text>
        </Space>
      ),
    },
    {
      title: 'Период',
      key: 'period',
      render: (_, r) => (
        <span>
          {r.date_from}
          {r.date_to ? ` — ${r.date_to}` : ' — ∞'}
        </span>
      ),
    },
    {
      title: 'Сумма',
      key: 'amt',
      render: (_, r) => r.contract_amount != null ? `${r.contract_amount} ${r.currency}` : '—',
    },
    {
      title: 'Статус',
      key: 'display_status',
      render: (_, r) => {
        const label = DISPLAY_LABELS[r.display_status] ?? r.display_status
        const color = r.display_status === 'expired' ? 'error' : r.display_status === 'refused' ? 'default' : 'success'
        return <Tag color={color}>{label}</Tag>
      },
    },
    {
      title: '',
      key: 'actions',
      width: 200,
      render: (_, r) => (
        <Space>
          {r.contract_file ? (
            <Button type="link" size="small" icon={<DownloadOutlined />} onClick={() => void handleDownload(r)}>
              Файл
            </Button>
          ) : null}
          <Button type="link" size="small" icon={<EditOutlined />} onClick={() => openEdit(r)}>
            Изменить
          </Button>
          <Button type="link" danger size="small" icon={<DeleteOutlined />} onClick={() => handleDelete(r)}>
            Удалить
          </Button>
        </Space>
      ),
    },
  ]

  return (
    <Card>
      <Space style={{ marginBottom: 8 }}>
        <RequestReturnBackButton fallbackPath="/contracts" fallbackLabel="Договоры" />
      </Space>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        Договоры
      </Typography.Title>
      {vendorFilter ? (
        <Typography.Paragraph type="secondary" style={{ marginBottom: 8 }}>
          Фильтр по поставщику: {vendorLabel.get(Number(vendorFilter)) ?? `#${vendorFilter}`}
        </Typography.Paragraph>
      ) : null}
      <Typography.Paragraph type="secondary">
        Договоры привязаны к поставщику из справочника. Файл хранится на сервере (до 10 МБ: pdf, офисные форматы,
        изображения).
      </Typography.Paragraph>
      {error ? <Alert type="error" showIcon message={error} style={{ marginBottom: 12 }} /> : null}
      <Space style={{ marginBottom: 12 }}>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
          Новый договор
        </Button>
        <Button onClick={load} loading={loading}>
          Обновить
        </Button>
      </Space>
      <Table<ContractRow>
        rowKey="id"
        loading={loading}
        dataSource={filteredRows}
        columns={columns}
        pagination={{ pageSize: 20 }}
        onRow={(record) =>
          record.is_expired
            ? {
                style: { background: '#fff1f0' },
              }
            : {}
        }
      />

      <Drawer
        title={editing ? 'Редактирование договора' : 'Новый договор'}
        width={480}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        destroyOnClose
        footer={
          <Space style={{ float: 'right' }}>
            <Button onClick={() => setDrawerOpen(false)}>Отмена</Button>
            <Button type="primary" loading={formLoading} onClick={() => void saveDrawer()}>
              Сохранить
            </Button>
          </Space>
        }
      >
        {formError ? <Alert type="error" showIcon message={formError} style={{ marginBottom: 12 }} /> : null}
        <Form form={form} layout="vertical">
          <Form.Item name="vendor" label="Поставщик" rules={[{ required: true, message: 'Выберите поставщика' }]}>
            <Select
              showSearch
              optionFilterProp="label"
              disabled={Boolean(editing)}
              options={vendors.map((v) => ({
                value: v.id,
                label: `${v.kind === 'cash' ? 'Наличные' : 'Перечисление'} · ${v.name}${v.inn ? ` · ИНН ${v.inn}` : ''}`,
              }))}
              placeholder="Из справочника"
            />
          </Form.Item>
          <Form.Item name="contract_number" label="Номер договора" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Space size={12} wrap style={{ width: '100%' }}>
            <Form.Item name="date_from" label="Дата с" rules={[{ required: true }]} style={{ flex: 1, minWidth: 140 }}>
              <Input type="date" />
            </Form.Item>
            <Form.Item name="date_to" label="Дата по" style={{ flex: 1, minWidth: 140 }}>
              <Input type="date" />
            </Form.Item>
          </Space>
          <Space size={12} wrap style={{ width: '100%' }}>
            <Form.Item name="contract_amount" label="Сумма" style={{ minWidth: 160 }}>
              <InputNumber min={0.01} step={0.01} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item name="currency" label="Валюта" rules={[{ required: true }]} style={{ width: 120 }}>
              <Select options={['UZS', 'USD', 'EUR', 'RUB'].map((c) => ({ value: c, label: c }))} />
            </Form.Item>
            <Form.Item name="contract_status" label="Решение" rules={[{ required: true }]} style={{ minWidth: 160 }}>
              <Select options={STATUS_OPTS} />
            </Form.Item>
          </Space>
          <Form.Item name="acc_number" label="Расчётный счёт (необяз.)">
            <Input />
          </Form.Item>
          <Form.Item name="contract_terms" label="Условия">
            <Input.TextArea rows={3} />
          </Form.Item>
          <Form.Item
            label="Файл договора"
            required={!editing}
            validateStatus={!editing && uploadFiles.length === 0 && formError ? 'error' : ''}
            help={!editing && uploadFiles.length === 0 && formError ? 'Прикрепите файл договора.' : undefined}
          >
            <Upload
              maxCount={1}
              fileList={uploadFiles}
              beforeUpload={() => false}
              onChange={({ fileList }) => setUploadFiles(fileList)}
            >
              <Button>Прикрепить файл</Button>
            </Upload>
          </Form.Item>
        </Form>
      </Drawer>
    </Card>
  )
}
