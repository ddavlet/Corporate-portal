import { Alert, Empty, Form, Input, Modal, Skeleton, Space, Table, Tabs, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'

import type { FundingPoolRequestDto } from '../../lib/api'
import { fundingTotalsText, groupByKind, type FundingMethod } from './fundingPool'
import { useInvestmentFromRequests } from './useInvestmentFromRequests'
import { asMoney, dateText } from './utils'

type Props = {
  open: boolean
  onCancel: () => void
  onCreated: () => Promise<void> | void
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

function Body({ onCancel, onCreated }: Omit<Props, 'open'>) {
  const collect = useInvestmentFromRequests()
  const { pool, loadError, method, selected, totals, comment } = collect

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
            collect.replaceSelection(
              list.map((r) => r.id),
              keys.map(Number),
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

  const submit = async () => {
    const created = await collect.submit()
    if (!created) return
    onCancel()
    try {
      await onCreated()
    } catch (e: unknown) {
      // Вложение уже создано — сбой перезагрузки списка не выдаём за ошибку создания.
      console.error('Failed to reload investments after collecting requests', e)
    }
  }

  return (
    <Modal
      open
      title="Вложение по заявкам"
      okText="Создать вложение"
      cancelText="Отмена"
      // Not canSubmit: it is false while sending, and a disabled button turns grey instead of showing the spinner.
      // A second send is blocked by confirmLoading and the hook itself.
      okButtonProps={{ disabled: !pool || collect.chosen.length === 0 || Boolean(collect.created) }}
      confirmLoading={collect.submitting}
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
              message="Вложения не будут подтверждаться — не настроено согласование"
            />
          ) : null}
          <Tabs
            activeKey={method}
            onChange={(k) => collect.setMethod(k as FundingMethod)}
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
            {fundingTotalsText(totals)}
          </Typography.Text>
          <Form layout="vertical">
            <Form.Item label="Описание">
              <Input.TextArea rows={3} maxLength={1000} value={comment} onChange={(e) => collect.setComment(e.target.value)} />
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
