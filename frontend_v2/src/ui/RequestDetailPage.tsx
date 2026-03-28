import { useEffect, useState } from 'react'
import { Alert, Button, Card, Space, Typography } from 'antd'
import { useNavigate, useParams } from 'react-router-dom'
import { apiFetch } from '../lib/api'
import { RequestDetailContent, type RequestDetail } from './RequestDetailModal'
import { NoteCreateModal } from './NoteCreateModal'

export type RequestDetailPageProps = {
  /** Путь к списку заявок для кнопки «Назад» */
  listPath?: string
}

export function RequestDetailPage({ listPath = '/requests' }: RequestDetailPageProps) {
  const navigate = useNavigate()
  const { id } = useParams<{ id: string }>()
  const [detail, setDetail] = useState<RequestDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [openNoteModal, setOpenNoteModal] = useState(false)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      if (!id) {
        setError('Request id is missing.')
        setLoading(false)
        return
      }
      setLoading(true)
      setError(null)
      try {
        const res = await apiFetch(`/api/requests/${id}/`)
        const json = (await res.json().catch(() => null)) as RequestDetail | null
        if (!res.ok) {
          throw new Error(typeof json === 'object' && json ? JSON.stringify(json) : `HTTP ${res.status}`)
        }
        if (!cancelled) setDetail(json)
      } catch (e: any) {
        if (!cancelled) setError(e?.message || 'Ошибка загрузки заявки')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [id])

  const openLinkedExpense = () => {
    if (!detail?.expense_link?.id) return
    const expId = String(detail.expense_link.id)
    if (detail.expense_link.module === 'cash') navigate(`/cash/${expId}`)
    if (detail.expense_link.module === 'bank') navigate(`/bank/${expId}`)
  }

  return (
    <Card>
      <Space direction="vertical" size={12} style={{ display: 'flex' }}>
        <Space>
          <Button onClick={() => navigate(listPath)}>Назад к списку</Button>
          {detail?.id ? <Button onClick={() => setOpenNoteModal(true)}>Добавить заметку</Button> : null}
          {detail?.expense_link?.id ? (
            <Button onClick={openLinkedExpense}>Открыть связанный расход</Button>
          ) : (
            <Typography.Text type="secondary">Связанный расход не найден</Typography.Text>
          )}
        </Space>
        {error && !loading ? <Alert type="error" showIcon message={error} /> : null}
        <RequestDetailContent detail={detail} loading={loading} error={error} />
      </Space>
      <NoteCreateModal
        open={openNoteModal}
        onCancel={() => setOpenNoteModal(false)}
        targetType="request"
        targetId={detail?.id || null}
      />
    </Card>
  )
}
