import { useEffect, useMemo, useState } from 'react'
import { Alert, Button, Card, Input, Skeleton, Space, Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useNavigate } from 'react-router-dom'
import { apiFetch } from '../lib/api'
import { labelBlockAboveField } from './formSpacing'

type PayrollDocumentRow = {
  id: number
  doc_id: string
  created_at: string
  total_sum: string | number
  lines_count: number
  has_request?: boolean
  has_paid_request?: boolean
  matched_request_id?: number | null
}

function normalizeRows(payload: unknown): PayrollDocumentRow[] {
  if (Array.isArray(payload)) return payload as PayrollDocumentRow[]
  if (payload && typeof payload === 'object' && 'results' in payload) {
    const results = (payload as { results?: unknown }).results
    return Array.isArray(results) ? (results as PayrollDocumentRow[]) : []
  }
  return []
}

export function PayrollPage() {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [rows, setRows] = useState<PayrollDocumentRow[]>([])
  const [docIdFilter, setDocIdFilter] = useState('')
  const [employeeSearch, setEmployeeSearch] = useState('')

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setLoading(true)
      setError(null)
      try {
        const params = new URLSearchParams()
        if (docIdFilter.trim()) params.set('doc_id', docIdFilter.trim())
        if (employeeSearch.trim()) params.set('employee_search', employeeSearch.trim())
        const q = params.toString()
        const res = await apiFetch(q ? `/api/payroll/documents/?${q}` : '/api/payroll/documents/')
        const json = await res.json().catch(() => null)
        if (!res.ok) {
          throw new Error(typeof json === 'object' && json ? JSON.stringify(json) : `HTTP ${res.status}`)
        }
        if (!cancelled) setRows(normalizeRows(json))
      } catch (e: unknown) {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Ошибка загрузки')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [docIdFilter, employeeSearch])

  const columns: ColumnsType<PayrollDocumentRow> = useMemo(
    () => [
      {
        title: 'Документ (doc_id)',
        dataIndex: 'doc_id',
        key: 'doc_id',
        render: (v: string, r) => (
          <Button type="link" onClick={() => navigate(`/payroll/${r.id}`)} style={{ padding: 0 }}>
            {v}
          </Button>
        ),
      },
      {
        title: 'Строк',
        dataIndex: 'lines_count',
        key: 'lines_count',
        width: 90,
      },
      {
        title: 'Сумма',
        dataIndex: 'total_sum',
        key: 'total_sum',
        width: 140,
        render: (v: string | number) => String(v ?? ''),
      },
      {
        title: 'Заявка',
        key: 'req',
        width: 200,
        render: (_, r) => (
          <Space size={4} wrap>
            {r.has_request ? <Tag color="blue">Есть заявка</Tag> : null}
            {r.has_paid_request ? <Tag color="green">Оплачено</Tag> : null}
            {r.matched_request_id ? (
              <Button type="link" size="small" onClick={() => navigate(`/requests/${r.matched_request_id}`)}>
                №{r.matched_request_id}
              </Button>
            ) : null}
          </Space>
        ),
      },
    ],
    [navigate],
  )

  return (
    <Card>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        Начисления ЗП
      </Typography.Title>
      <Typography.Paragraph type="secondary">
        Документы начислений по <span className="mono">doc_id</span>; заявки (наличные, категория зарплаты) привязываются к
        документу.
      </Typography.Paragraph>
      <Space wrap style={{ marginBottom: 16 }} align="end">
        <div>
          <Typography.Text style={labelBlockAboveField}>Фильтр doc_id</Typography.Text>
          <Input
            allowClear
            placeholder="doc_id"
            value={docIdFilter}
            onChange={(e) => setDocIdFilter(e.target.value)}
            style={{ width: 220 }}
          />
        </div>
        <div>
          <Typography.Text style={labelBlockAboveField}>Сотрудник</Typography.Text>
          <Input
            allowClear
            placeholder="поиск по ФИО"
            value={employeeSearch}
            onChange={(e) => setEmployeeSearch(e.target.value)}
            style={{ width: 220 }}
          />
        </div>
      </Space>
      {loading ? <Skeleton active /> : null}
      {error ? <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} /> : null}
      {!loading && !error ? (
        <Table<PayrollDocumentRow>
          rowKey="id"
          columns={columns}
          dataSource={rows}
          pagination={{ pageSize: 50, showSizeChanger: true }}
        />
      ) : null}
    </Card>
  )
}
