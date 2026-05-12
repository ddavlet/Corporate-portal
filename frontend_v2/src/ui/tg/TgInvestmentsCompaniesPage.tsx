import { useEffect, useMemo, useState } from 'react'
import { Alert, Button, Input, Skeleton, Tag, Typography } from 'antd'
import { useNavigate } from 'react-router-dom'
import { ArrowLeftOutlined, SearchOutlined } from '@ant-design/icons'
import { getInvestCompanies, type InvestCompanyRow } from '../../lib/api'

export function TgInvestmentsCompaniesPage() {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [rows, setRows] = useState<InvestCompanyRow[]>([])
  const [search, setSearch] = useState('')

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setError(null)
      setLoading(true)
      try {
        const data = await getInvestCompanies()
        if (!cancelled) setRows(data)
      } catch (e: unknown) {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Ошибка загрузки')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    const sorted = [...rows].sort((a, b) => a.name.localeCompare(b.name))
    if (!q) return sorted
    return sorted.filter((row) => JSON.stringify(row).toLowerCase().includes(q))
  }, [rows, search])

  return (
    <div className="tg-investments-page">
      <Button
        icon={<ArrowLeftOutlined />}
        size="large"
        onClick={() => navigate('/tg/investments')}
        style={{ marginBottom: 12, borderRadius: 12 }}
      >
        Назад
      </Button>

      <Typography.Title level={4} style={{ margin: '0 0 16px', fontWeight: 700 }}>
        Компании
      </Typography.Title>

      <div className="tg-list-search">
        <Input
          size="large"
          placeholder="Поиск…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          allowClear
          prefix={<SearchOutlined style={{ color: 'var(--tg-hint, #999)' }} />}
        />
      </div>

      {error ? (
        <Alert type="error" showIcon message={error} style={{ marginBottom: 12, borderRadius: 12 }} />
      ) : null}
      {loading ? <Skeleton active paragraph={{ rows: 6 }} /> : null}

      {!loading && !error && filtered.length === 0 ? (
        <Typography.Paragraph type="secondary" style={{ textAlign: 'center', padding: '24px 8px' }}>
          {rows.length === 0 ? 'Компаний пока нет.' : 'Ничего не найдено.'}
        </Typography.Paragraph>
      ) : null}

      {!loading && !error
        ? filtered.map((row) => (
            <div key={row.id} className="tg-request-row" style={{ cursor: 'default' }}>
              <div className="tg-request-row-title">{row.name || `Компания #${row.id}`}</div>
              <div className="tg-request-row-meta">
                <Tag color={row.is_active ? 'green' : 'default'}>
                  {row.is_active ? 'Активна' : 'Неактивна'}
                </Tag>
                {row.comment ? <span>{row.comment}</span> : null}
              </div>
            </div>
          ))
        : null}
    </div>
  )
}
