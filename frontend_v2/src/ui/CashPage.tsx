import { useEffect, useState } from 'react'
import { Alert, Card, Skeleton, Typography } from 'antd'
import { apiFetch } from '../lib/api'

export function CashPage() {
  const [loading, setLoading] = useState(true)
  const [data, setData] = useState<any>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setError(null)
      setLoading(true)
      try {
        const res = await apiFetch('/api/cash/expenses/')
        const json = await res.json().catch(() => null)
        if (!cancelled) setData({ status: res.status, json })
      } catch (e: any) {
        if (!cancelled) setError(e?.message || 'Ошибка запроса')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <Card>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        Кассовые расходы
      </Typography.Title>
      <Typography.Text type="secondary">
        Запрос: <span className="mono">GET /api/cash/expenses/</span>
      </Typography.Text>
      {loading ? <Skeleton active style={{ marginTop: 16 }} /> : null}
      {error ? <Alert type="error" showIcon message={error} style={{ marginTop: 16 }} /> : null}
      {!loading ? (
        <pre className="json-preview">
          {JSON.stringify(data, null, 2)}
        </pre>
      ) : null}
    </Card>
  )
}

