import { useEffect, useMemo, useState, type Key } from 'react'
import { Alert, Empty, Form, Input, Modal, Select, Skeleton, Space, Table, Tabs, Tag, Typography, message } from 'antd'
import type { ColumnsType } from 'antd/es/table'

import {
  createInvestmentsFromRequests,
  getFundingPool,
  type FundingPoolDto,
  type FundingPoolRequestDto,
  type InvestCompanyRow,
} from '../../lib/api'
import { defaultCollectComment, groupByKind, totalsByCurrency, type FundingMethod } from './fundingPool'
import { asMoney, dateText, makeCompanySelectOptions } from './utils'

type Props = {
  open: boolean
  onCancel: () => void
  onCreated: () => Promise<void> | void
  usesCompanies: boolean
  companies: InvestCompanyRow[]
}

const columns: ColumnsType<FundingPoolRequestDto> = [
  { title: '№', dataIndex: 'id', width: 80 },
  {
    title: 'Дата',
    dataIndex: 'submitted_at',
    width: 110,
    render: (v: string | null) => (v ? dateText(v) : '—'),
  },
  { title: 'Назначение', dataIndex: 'payment_purpose', render: (v: string) => v || '—' },
  { title: 'Описание', dataIndex: 'description', render: (v: string) => v || '—' },
  { title: 'Сумма', dataIndex: 'amount', width: 140, align: 'right', render: (v: string) => asMoney(v) },
  { title: 'Валюта', dataIndex: 'currency', width: 80 },
  {
    title: '',
    dataIndex: 'is_payed',
    width: 110,
    render: (v: boolean) => (v ? <Tag color="success">Выплачена</Tag> : null),
  },
]

function totalLine(total: { currency: string; amount: number; count: number }): string {
  const n = total.count
  const word = n % 10 === 1 && n % 100 !== 11 ? 'заявка' : n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 10 || n % 100 >= 20) ? 'заявки' : 'заявок'
  return `${asMoney(total.amount)} ${total.currency} (${n} ${word})`
}

function Body({ onCancel, onCreated, usesCompanies, companies }: Omit<Props, 'open'>) {
  const [pool, setPool] = useState<FundingPoolDto | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [method, setMethod] = useState<FundingMethod>('cash')
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [editedComment, setEditedComment] = useState<string | null>(null)
  const [company, setCompany] = useState<number | null>(null)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    let cancelled = false
    getFundingPool()
      .then((data) => {
        if (cancelled) return
        setPool(data)
        setSelected(new Set([...data.cash.requests, ...data.bank_transfer.requests].map((r) => r.id)))
      })
      .catch((e: unknown) => {
        if (!cancelled) setLoadError(e instanceof Error ? e.message : 'Не удалось загрузить заявки')
      })
    return () => {
      cancelled = true
    }
  }, [])

  const rows = useMemo(() => (pool ? pool[method].requests : []), [pool, method])
  const chosen = useMemo(() => rows.filter((r) => selected.has(r.id)), [rows, selected])
  const totals = useMemo(() => totalsByCurrency(rows, selected), [rows, selected])
  const generated = useMemo(() => defaultCollectComment(chosen), [chosen])
  const comment = editedComment ?? generated

  const toggle = (ids: number[], keys: Key[]) => {
    setSelected((prev) => {
      const next = new Set(prev)
      ids.forEach((id) => next.delete(id))
      keys.forEach((k) => next.add(Number(k)))
      return next
    })
  }

  const renderTable = (title: string | null, list: FundingPoolRequestDto[]) => (
    <Space direction="vertical" size={4} style={{ width: '100%' }}>
      {title ? <Typography.Text strong>{title}</Typography.Text> : null}
      <Table
        rowKey="id"
        size="small"
        columns={columns}
        dataSource={list}
        pagination={false}
        rowSelection={{
          selectedRowKeys: list.filter((r) => selected.has(r.id)).map((r) => r.id),
          onChange: (keys) =>
            toggle(
              list.map((r) => r.id),
              keys,
            ),
        }}
        scroll={{ x: 700 }}
        locale={{ emptyText: 'Нет заявок' }}
      />
    </Space>
  )

  const renderTab = (m: FundingMethod) => {
    const list = pool ? pool[m].requests : []
    if (list.length === 0) return <Empty description="Нет заявок для сбора" image={Empty.PRESENTED_IMAGE_SIMPLE} />
    if (m === 'bank_transfer') return renderTable(null, list)
    const groups = groupByKind(list)
    return (
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        {renderTable('Расходы', groups.expense)}
        {renderTable('Перемещения', groups.transfer)}
      </Space>
    )
  }

  const companyMissing = usesCompanies && company == null
  const canSubmit = chosen.length > 0 && !companyMissing

  const submit = async () => {
    setSubmitting(true)
    try {
      const res = await createInvestmentsFromRequests({
        funding_method: method,
        request_ids: chosen.map((r) => r.id),
        comment,
        ...(usesCompanies ? { company } : {}),
      })
      const ids = res.investments.map((i) => `№${i.id}`).join(', ')
      message.success(`Создано вложений: ${ids}`)
      onCancel()
      await onCreated()
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : 'Не удалось создать вложение')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal
      open
      title="Вложение по заявкам"
      okText="Создать вложение"
      cancelText="Отмена"
      okButtonProps={{ disabled: !pool || !canSubmit }}
      confirmLoading={submitting}
      onOk={() => void submit()}
      onCancel={onCancel}
      width={900}
    >
      {loadError ? <Alert type="error" showIcon message={loadError} /> : null}
      {!pool && !loadError ? <Skeleton active /> : null}
      {pool ? (
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          {!pool.approval_chain_ok ? (
            <Alert
              type="warning"
              showIcon
              message="Не настроена цепочка согласования вложений: вложение будет создано без этапов согласования."
            />
          ) : null}
          <Tabs
            activeKey={method}
            onChange={(k) => {
              setMethod(k as FundingMethod)
              setEditedComment(null)
            }}
            items={[
              { key: 'cash', label: `Наличными (${pool.cash.requests.length})`, children: renderTab('cash') },
              {
                key: 'bank_transfer',
                label: `Переводом на счёт (${pool.bank_transfer.requests.length})`,
                children: renderTab('bank_transfer'),
              },
            ]}
          />
          <Typography.Text strong>
            {totals.length === 0 ? 'Итого: ничего не выбрано' : `Итого: ${totals.map(totalLine).join('; ')}`}
          </Typography.Text>
          <Form layout="vertical">
            {usesCompanies ? (
              <Form.Item label="Компания" required validateStatus={companyMissing ? 'error' : undefined}>
                <Select
                  value={company ?? undefined}
                  onChange={(v) => setCompany(v ?? null)}
                  options={makeCompanySelectOptions(companies)}
                  placeholder="Выберите компанию"
                />
              </Form.Item>
            ) : null}
            <Form.Item label="Описание">
              <Input.TextArea rows={3} maxLength={1000} value={comment} onChange={(e) => setEditedComment(e.target.value)} />
            </Form.Item>
          </Form>
        </Space>
      ) : null}
    </Modal>
  )
}

export function InvestmentFromRequestsModal(props: Props) {
  if (!props.open) return null
  return <Body {...props} />
}
