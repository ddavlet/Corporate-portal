import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { RequestReturnBackButton } from '../requests/RequestReturnBackButton'
import { Alert, Button, Card, Col, Form, Input, InputNumber, Modal, Popconfirm, Row, Select, Space, Switch, Table, Typography, message } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  fetchAdminCrudPostSchema,
  planAdminCreateFieldsFromOptionsPost,
  planAdminCreateFieldsFromRow,
  type AdminCrudDynamicField,
} from '../../lib/adminModuleCrudFields'
import { apiFetch, getAccessMatrix, type AccessMatrixRoleModuleRow } from '../../lib/api'
import { getFieldLabel } from '../../lib/adminFieldLabels'
import { useInfiniteList } from '../../lib/useInfiniteList'
import { ListInfiniteScrollFooter } from '../ListInfiniteScrollFooter'
import { tenantRoleLabel } from '../../lib/tenantRoles'
import { AdminRecordEditModal, extractApiError } from './AdminRecordEditModal'

type AnyRow = Record<string, unknown> & { id?: number | string }

type Source = {
  key: string
  label: string
  endpoint: string
  /** false — источник read-only или POST не соответствует таблице (напр. только создание без списка). */
  supportsCreate?: boolean
  /** Только GET-список: без создания, правки и удаления в UI. */
  readOnly?: boolean
}

const SOURCES: Source[] = [
  { key: 'vendors', label: 'Поставщики', endpoint: '/api/vendors/' },
  { key: 'requests', label: 'Заявки', endpoint: '/api/requests/' },
  { key: 'notes', label: 'Заметки', endpoint: '/api/notes/', supportsCreate: false },
  { key: 'payroll-documents', label: 'Начисления ЗП: документы', endpoint: '/api/payroll/documents/', supportsCreate: false },
  { key: 'clients-debt', label: 'Долги клиентов', endpoint: '/api/clients-debt/', supportsCreate: false },
  { key: 'cash-expenses', label: 'Касса: расходы', endpoint: '/api/cash/expenses/' },
  { key: 'cash-revenues', label: 'Касса: доходы', endpoint: '/api/cash/revenues/' },
  { key: 'bank-expenses', label: 'Банк: расходы', endpoint: '/api/bank/expenses/' },
  { key: 'bank-revenues', label: 'Банк: доходы', endpoint: '/api/bank/revenues/' },
  { key: 'card-expenses', label: 'Корпкарта: расходы', endpoint: '/api/corporate-card/expenses/' },
  { key: 'card-revenues', label: 'Корпкарта: доходы', endpoint: '/api/corporate-card/revenues/' },
  { key: 'wallets-cash-registers', label: 'Кошельки: кассы', endpoint: '/api/wallets/cash-registers/' },
  { key: 'wallets-bank-accounts', label: 'Кошельки: счета', endpoint: '/api/wallets/bank-accounts/' },
  {
    key: 'wallets-corporate-card-accounts',
    label: 'Кошельки: корпоративные карты',
    endpoint: '/api/wallets/corporate-card-accounts/',
  },
  { key: 'invest-companies', label: 'Инвестиции: компании', endpoint: '/api/investments/companies/' },
  { key: 'invest-returns', label: 'Инвестиции: выплаты', endpoint: '/api/investments/returns/' },
  { key: 'invest-payout-schedule', label: 'Инвестиции: график выплат', endpoint: '/api/investments/payout-schedule/' },
  { key: 'invest-project-investments', label: 'Инвестиции: вложения в проект', endpoint: '/api/investments/project-investments/' },
]

function normalizeRows(payload: unknown): AnyRow[] {
  if (Array.isArray(payload)) return payload as AnyRow[]
  if (payload && typeof payload === 'object' && 'results' in payload) {
    const results = (payload as { results?: unknown }).results
    return Array.isArray(results) ? (results as AnyRow[]) : []
  }
  return []
}

type RoleMatrixRow = {
  key: string
  role: string
  module_access: Record<string, boolean>
}

type AdminSectionKey = 'matrix' | 'crud'

function rowCaption(row: AnyRow): string {
  const counterparty = String(row.vendor_name ?? '').trim()
  return String(
    row.title ??
      row.name ??
      row.label ??
      (counterparty || undefined) ??
      row.external_id ??
      row.doc_no ??
      row.operation ??
      row.token ??
      row.decision ??
      row.type ??
      row.recipient ??
      (typeof row.comment === 'string' && row.comment.trim() ? row.comment.trim() : undefined) ??
      row.id ??
      'Запись',
  )
}

function formatAmount(value: unknown): string | null {
  if (value === null || value === undefined || value === '') return null
  const asNumber = typeof value === 'number' ? value : Number(String(value).replace(/\s+/g, '').replace(',', '.'))
  if (!Number.isFinite(asNumber)) return null
  return new Intl.NumberFormat('ru-RU', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(asNumber)
}

export function AdminModulePage() {
  const [searchParams] = useSearchParams()
  const [form] = Form.useForm<Record<string, unknown>>()
  const [activeSection, setActiveSection] = useState<AdminSectionKey>('matrix')
  const [sourceKey, setSourceKey] = useState<string>(SOURCES[0].key)
  const [search, setSearch] = useState('')
  const [editing, setEditing] = useState<AnyRow | null>(null)
  const [editableFields, setEditableFields] = useState<AdminCrudDynamicField[]>([])
  const [nonEditableFields, setNonEditableFields] = useState<Array<{ key: string; value: unknown }>>([])
  const [saving, setSaving] = useState(false)

  /** Создание новой записи (модальное окно). */
  const [creatingRecord, setCreatingRecord] = useState(false)
  const [openingCreateModal, setOpeningCreateModal] = useState(false)

  const [mxLoading, setMxLoading] = useState(false)
  const [mxError, setMxError] = useState<string | null>(null)
  const [roleMatrixRows, setRoleMatrixRows] = useState<AccessMatrixRoleModuleRow[]>([])
  const [mxModules, setMxModules] = useState<Array<{ module_key: string; display_name: string }>>([])
  const [matrixPage, setMatrixPage] = useState(1)
  const [matrixPageSize, setMatrixPageSize] = useState(20)

  const currentSource = SOURCES.find((s) => s.key === sourceKey) || SOURCES[0]
  const canCreateHere = Boolean(!currentSource.readOnly && currentSource.supportsCreate !== false)

  const {
    items: rows,
    loading,
    loadingMore,
    error,
    hasMore,
    reload: loadRows,
    sentinelRef,
  } = useInfiniteList<AnyRow>({ url: currentSource.endpoint })

  const loadMatrix = async () => {
    setMxLoading(true)
    setMxError(null)
    try {
      const data = await getAccessMatrix()
      setRoleMatrixRows(data.role_module_rows)
      setMxModules(data.modules)
    } catch (e: unknown) {
      setRoleMatrixRows([])
      setMxModules([])
      setMxError(e instanceof Error ? e.message : 'Не удалось загрузить матрицу доступов')
    } finally {
      setMxLoading(false)
    }
  }

  useEffect(() => {
    const source = searchParams.get('source')
    if (source && SOURCES.some((item) => item.key === source)) {
      setSourceKey(source)
      setActiveSection('crud')
    }
  }, [searchParams])

  useEffect(() => {
    const rowId = searchParams.get('row')
    if (!rowId || rows.length === 0) return
    const found = rows.find((row) => String(row.id) === rowId)
    if (found) setSearch(rowCaption(found))
  }, [rows, searchParams])

  useEffect(() => {
    void loadMatrix()
  }, [])

  const filteredRows = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return rows
    return rows.filter((row) => rowCaption(row).toLowerCase().includes(q) || JSON.stringify(row).toLowerCase().includes(q))
  }, [rows, search])

  const matrixRows = useMemo<RoleMatrixRow[]>(
    () => roleMatrixRows.map((row) => ({ ...row, key: row.role })),
    [roleMatrixRows],
  )

  const handleDelete = async (row: AnyRow) => {
    const id = row.id
    if (id === undefined || id === null || id === '') {
      message.error('У записи отсутствует id')
      return
    }
    const res = await apiFetch(`${currentSource.endpoint}${id}/`, { method: 'DELETE' })
    if (!res.ok) {
      const json = await res.json().catch(() => null)
      message.error(extractApiError(json, res.status))
      return
    }
    message.success('Удалено')
    await loadRows()
  }

  const baseCrudColumns: ColumnsType<AnyRow> = [
    { title: 'ID', dataIndex: 'id', width: 100, render: (v: unknown) => String(v ?? '-') },
    {
      title: 'Название',
      key: 'summary',
      render: (_, row) => <Typography.Text ellipsis style={{ maxWidth: 520 }}>{rowCaption(row)}</Typography.Text>,
    },
    {
      title: 'Кратко',
      key: 'short',
      render: (_, row) => {
        const parts: string[] = []
        const counterparty = String(row.vendor_name ?? '').trim()
        if (counterparty) parts.push(`Контрагент: ${counterparty}`)
        if (typeof row.status === 'string' && row.status) parts.push(`Статус: ${row.status}`)
        if (typeof row.decision === 'string' && row.decision) parts.push(`Решение: ${row.decision}`)
        if (typeof row.step_type === 'string' && row.step_type) parts.push(`Тип шага: ${row.step_type}`)
        if (typeof row.is_enabled === 'boolean') parts.push(`Вкл: ${row.is_enabled ? 'да' : 'нет'}`)
        if (typeof row.is_paid === 'boolean') parts.push(`Оплачено: ${row.is_paid ? 'да' : 'нет'}`)
        if (typeof row.confirmed === 'boolean') parts.push(`Подтв.: ${row.confirmed ? 'да' : 'нет'}`)
        if (typeof row.currency === 'string' && row.currency) parts.push(`Валюта: ${row.currency}`)
        const amountLike = row.debt_sum ?? row.amount ?? row.total_sum ?? row.sum ?? row.payment_amount
        const formattedAmount = formatAmount(amountLike)
        if (formattedAmount !== null) parts.push(`Сумма: ${formattedAmount}`)
        return <Typography.Text type="secondary">{parts.join(' | ') || '—'}</Typography.Text>
      },
    },
  ]

  const columns: ColumnsType<AnyRow> = currentSource.readOnly
    ? baseCrudColumns
    : [
        ...baseCrudColumns,
        {
          title: 'Действия',
          key: 'actions',
          width: 210,
          render: (_, row) => (
            <Space>
              <Button
                size="small"
                onClick={() => {
                  setCreatingRecord(false)
                  setEditing(row)
                }}
              >
                Изменить
              </Button>
              <Popconfirm title="Удалить запись?" description={rowCaption(row)} onConfirm={() => void handleDelete(row)}>
                <Button size="small" danger>
                  Удалить
                </Button>
              </Popconfirm>
            </Space>
          ),
        },
      ]
  const matrixColumns: ColumnsType<RoleMatrixRow> = useMemo(() => {
    const base: ColumnsType<RoleMatrixRow> = [
      {
        title: 'Роль',
        dataIndex: 'role',
        width: 220,
        fixed: 'left',
        render: (role: string) => tenantRoleLabel(role),
      },
    ]
    const mods: ColumnsType<RoleMatrixRow> = mxModules.map((m) => ({
      title: m.display_name,
      key: `mod_${m.module_key}`,
      width: 120,
      align: 'center',
      render: (_, row) => (row.module_access?.[m.module_key] ? 'Да' : '—'),
    }))
    return [...base, ...mods]
  }, [mxModules])

  const closeRecordModal = () => {
    setEditing(null)
    setCreatingRecord(false)
    setEditableFields([])
    setNonEditableFields([])
    form.resetFields()
  }

  const openCreateModal = async () => {
    setOpeningCreateModal(true)
    try {
      let plan =
        planAdminCreateFieldsFromOptionsPost(
          await fetchAdminCrudPostSchema(currentSource.endpoint, apiFetch),
        ) ?? null

      const templateRow = (filteredRows[0] ?? rows[0]) as AnyRow | undefined
      if ((!plan || !plan.fields.length) && templateRow) {
        plan = planAdminCreateFieldsFromRow(templateRow as Record<string, unknown>)
      }

      if (!plan || !plan.fields.length) {
        message.warning(
          'Не удалось сформировать поля: откройте OPTIONS у API или дождитесь строк в таблице и нажмите «Обновить».',
        )
        return
      }

      setEditing(null)
      setCreatingRecord(true)
      setEditableFields(plan.fields)
      setNonEditableFields(plan.nonEditable)
      form.resetFields()
      // plan.initial — Record<string, unknown> из DRF/строки; Ant Form ожидает более узкий Store.
      form.setFieldsValue(plan.initial as unknown as Parameters<typeof form.setFieldsValue>[0])
    } finally {
      setOpeningCreateModal(false)
    }
  }

  const handleCreateRecord = async () => {
    const payload = (await form.validateFields()) as Record<string, unknown>
    const body: Record<string, unknown> = {}
    for (const [key, raw] of Object.entries(payload)) {
      if (raw === undefined) continue
      body[key] = raw
    }
    setSaving(true)
    try {
      const res = await apiFetch(currentSource.endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const json = await res.json().catch(() => null)
      if (!res.ok) throw new Error(extractApiError(json, res.status))
      message.success('Создано')
      closeRecordModal()
      await loadRows()
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : 'Не удалось создать запись')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div style={{ maxWidth: 1500 }}>
      <RequestReturnBackButton fallbackPath="/admin" fallbackLabel="Админка" />
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        Админка
      </Typography.Title>
      <Typography.Paragraph type="secondary">
        Доступна только администратору компании (роль admin в tenant). Матрица показывает статические права ролей по
        модулям; назначение ролей пользователям — в Настройки → Настройки пользователей. Фактический доступ также
        зависит от включения модуля у компании.
      </Typography.Paragraph>
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
            <Col xs={24} sm={12} lg={8}>
              <Card
                hoverable
                title="Матрица доступов"
                onClick={() => setActiveSection('matrix')}
                style={{ borderColor: activeSection === 'matrix' ? '#1677ff' : undefined }}
              >
                <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
                  Какие роли tenant открывают какие модули (статическая матрица из кода).
                </Typography.Paragraph>
              </Card>
            </Col>
            <Col xs={24} sm={12} lg={8}>
              <Card
                hoverable
                title="Данные модулей"
                onClick={() => setActiveSection('crud')}
                style={{ borderColor: activeSection === 'crud' ? '#1677ff' : undefined }}
              >
                <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
                  User-friendly редактирование и удаление записей.
                </Typography.Paragraph>
              </Card>
            </Col>
          </Row>

          {activeSection === 'matrix' ? (
            <Card
              title="Роль × модуль"
              extra={
                <Button onClick={() => void loadMatrix()} loading={mxLoading}>
                  Обновить
                </Button>
              }
            >
              {mxError ? <Alert type="error" showIcon message={mxError} style={{ marginBottom: 12 }} /> : null}
              <Typography.Paragraph type="secondary">
                «Да» — роль даёт доступ к модулю при активном членстве в компании и включённом модуле. Пусто — нет
                доступа по этой роли.
              </Typography.Paragraph>
              <Table<RoleMatrixRow>
                loading={mxLoading}
                columns={matrixColumns}
                dataSource={matrixRows}
                pagination={{
                  current: matrixPage,
                  pageSize: matrixPageSize,
                  showSizeChanger: true,
                }}
                onChange={(pagination) => {
                  if (pagination.current) setMatrixPage(pagination.current)
                  if (pagination.pageSize) setMatrixPageSize(pagination.pageSize)
                }}
                scroll={{ x: 1200 }}
              />
            </Card>
          ) : (
            <Card>
              <Space wrap style={{ marginBottom: 12 }}>
                <Select
                  style={{ width: 320 }}
                  value={sourceKey}
                  options={SOURCES.map((s) => ({ value: s.key, label: s.label }))}
                  onChange={(v) => setSourceKey(v)}
                />
                <Input
                  placeholder="Поиск: id, название, номер, статус"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  allowClear
                  style={{ width: 300 }}
                />
                <Button onClick={() => void loadRows()}>Обновить</Button>
                {canCreateHere ? (
                  <Button type="primary" loading={openingCreateModal} onClick={() => void openCreateModal()}>
                    Создать
                  </Button>
                ) : null}
              </Space>
              {error ? <Alert type="error" showIcon message={error} style={{ marginBottom: 12 }} /> : null}
              <Table<AnyRow>
                rowKey={(row) => String(row.id ?? JSON.stringify(row))}
                loading={loading}
                columns={columns}
                dataSource={filteredRows}
                pagination={false}
                scroll={{ x: 1200 }}
              />
              <ListInfiniteScrollFooter
                sentinelRef={sentinelRef}
                hasMore={hasMore}
                loadingMore={loadingMore}
                visibleCount={filteredRows.length}
              />
            </Card>
          )}

      <Modal
        open={creatingRecord}
        title={`Создать запись · ${currentSource.label}`}
        okText="Создать"
        onOk={() => void handleCreateRecord()}
        confirmLoading={saving}
        onCancel={closeRecordModal}
        width={920}
      >
        <Form form={form} layout="vertical">
          {editableFields.map(({ key, type, choices }) => {
              if (choices?.length) {
                return (
                  <Form.Item key={key} label={getFieldLabel(key)} name={key}>
                    <Select
                      allowClear
                      showSearch
                      optionFilterProp="label"
                      options={choices.map((c) => ({ value: c.value, label: c.label }))}
                      placeholder={`Выберите ${getFieldLabel(key)}`}
                    />
                  </Form.Item>
                )
              }
              if (type === 'boolean') {
                return (
                  <Form.Item key={key} label={getFieldLabel(key)} name={key} valuePropName="checked">
                    <Switch />
                  </Form.Item>
                )
              }
              if (type === 'number') {
                return (
                  <Form.Item key={key} label={getFieldLabel(key)} name={key}>
                    <InputNumber style={{ width: '100%' }} />
                  </Form.Item>
                )
              }
              return (
                <Form.Item key={key} label={getFieldLabel(key)} name={key}>
                  <Input allowClear />
                </Form.Item>
              )
            })}
        </Form>
        {nonEditableFields.length ? (
          <Alert
            type="info"
            showIcon
            message="Поля из образца строки задаются только на сервере или через расширенный API"
            description={
              <Space direction="vertical">
                {nonEditableFields.map((f) => (
                  <Typography.Text key={f.key} type="secondary">
                    {getFieldLabel(f.key)}: {JSON.stringify(f.value)}
                  </Typography.Text>
                ))}
              </Space>
            }
          />
        ) : null}
      </Modal>

      <AdminRecordEditModal
        endpoint={currentSource.endpoint}
        record={editing}
        open={Boolean(editing)}
        onClose={() => setEditing(null)}
        onSaved={() => void loadRows()}
        title={editing ? `Изменить: ${rowCaption(editing)}` : undefined}
      />
    </div>
  )
}

