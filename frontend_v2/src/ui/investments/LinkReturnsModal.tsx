import { useEffect, useState } from 'react'
import { Empty, Modal, Skeleton, Table, message } from 'antd'
import type { ColumnsType } from 'antd/es/table'

import {
  getUnlinkedInvestReturns,
  linkReturnsToSchedule,
  type InvestPayoutScheduleRow,
  type InvestReturnRow,
} from '../../lib/api'
import { asMoney, dateText } from './utils'

type Props = {
  open: boolean
  schedule: InvestPayoutScheduleRow | null
  onCancel: () => void
  onLinked: () => Promise<void> | void
}

export function LinkReturnsModal({ open, schedule, onCancel, onLinked }: Props) {
  const [loading, setLoading] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [rows, setRows] = useState<InvestReturnRow[]>([])
  const [selectedIds, setSelectedIds] = useState<number[]>([])

  useEffect(() => {
    if (!open || !schedule) return
    setSelectedIds([])
    setLoading(true)
    getUnlinkedInvestReturns(schedule.company)
      .then(setRows)
      .catch((e: unknown) => message.error(e instanceof Error ? e.message : 'Не удалось загрузить выплаты'))
      .finally(() => setLoading(false))
  }, [open, schedule])

  const submit = async () => {
    if (!schedule || selectedIds.length === 0) return
    setSubmitting(true)
    try {
      const res = await linkReturnsToSchedule(schedule.id, selectedIds)
      message.success(res.detail || 'Выплаты привязаны')
      await onLinked()
      onCancel()
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : 'Не удалось привязать выплаты')
    } finally {
      setSubmitting(false)
    }
  }

  const columns: ColumnsType<InvestReturnRow> = [
    { title: 'ID', dataIndex: 'id', width: 70 },
    { title: 'Дата', dataIndex: 'date', width: 110, render: (v: string) => dateText(v) },
    { title: 'Сумма', dataIndex: 'sum', width: 130, align: 'right', render: (v: string | number) => asMoney(v) },
    { title: 'Валюта', dataIndex: 'currency', width: 80 },
    { title: 'Тип', dataIndex: 'type', width: 140 },
    { title: 'Получатель', dataIndex: 'recipient', width: 110 },
    { title: 'Комментарий', dataIndex: 'comment', render: (v: string) => v || '-' },
  ]

  return (
    <Modal
      open={open}
      title={schedule ? `Привязать выплаты к расписанию #${schedule.id}` : 'Привязать выплаты'}
      okText="Привязать"
      cancelText="Отмена"
      confirmLoading={submitting}
      onOk={submit}
      onCancel={onCancel}
      okButtonProps={{ disabled: selectedIds.length === 0 }}
      destroyOnClose
      width={760}
    >
      {loading ? (
        <Skeleton active />
      ) : (
        <Table
          rowKey="id"
          size="small"
          columns={columns}
          dataSource={rows}
          pagination={{ pageSize: 10 }}
          rowSelection={{
            selectedRowKeys: selectedIds,
            onChange: (keys) => setSelectedIds(keys as number[]),
          }}
          locale={{
            emptyText: <Empty description="Непривязанных выплат этой компании нет" image={Empty.PRESENTED_IMAGE_SIMPLE} />,
          }}
        />
      )}
    </Modal>
  )
}
