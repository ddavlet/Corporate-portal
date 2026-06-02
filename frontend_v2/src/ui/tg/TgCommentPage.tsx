import { useCallback, useEffect, useRef, useState } from 'react'
import { Alert, Button, Card, Empty, Input, List, Spin, Typography, message } from 'antd'
import { useSearchParams } from 'react-router-dom'
import { createRequestComment, listRequestComments, type RequestComment } from '../../lib/api'
import { resolveCommentRequestId } from './tgCommentRequestId'

const COMMENT_MAX_LENGTH = 4000

const dateTimeFormatter = new Intl.DateTimeFormat('ru-RU', {
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  timeZone: 'Asia/Tashkent',
})

function formatDateTime(value?: string | null): string {
  if (!value) return ''
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return ''
  return dateTimeFormatter.format(d)
}

export function TgCommentPage() {
  const [searchParams] = useSearchParams()
  const [body, setBody] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [requestId, setRequestId] = useState(0)
  const [comments, setComments] = useState<RequestComment[]>([])
  const [loadingComments, setLoadingComments] = useState(false)
  const [listError, setListError] = useState<string | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    let alive = true
    const sync = () => {
      if (!alive) return
      const next = resolveCommentRequestId(searchParams)
      setRequestId((prev) => (prev !== next ? next : prev))
    }
    sync()
    window.Telegram?.WebApp?.ready?.()
    const raf = requestAnimationFrame(sync)
    const t0 = window.setTimeout(sync, 0)
    const t1 = window.setTimeout(sync, 50)
    const t2 = window.setTimeout(sync, 250)
    return () => {
      alive = false
      cancelAnimationFrame(raf)
      window.clearTimeout(t0)
      window.clearTimeout(t1)
      window.clearTimeout(t2)
    }
  }, [searchParams])

  const isRequestValid = Number.isInteger(requestId) && requestId > 0

  const loadComments = useCallback(async () => {
    if (!isRequestValid) return
    setLoadingComments(true)
    setListError(null)
    try {
      const items = await listRequestComments(requestId)
      setComments(items)
    } catch (e: unknown) {
      setListError(e instanceof Error ? e.message : 'Не удалось загрузить комментарии')
    } finally {
      setLoadingComments(false)
    }
  }, [isRequestValid, requestId])

  useEffect(() => {
    void loadComments()
  }, [loadComments])

  const submit = async () => {
    const trimmed = body.trim()
    if (!isRequestValid) {
      setError('Не найден request_id. Откройте эту страницу через кнопку в сообщении бота.')
      return
    }
    if (!trimmed) {
      setError('Введите текст комментария.')
      return
    }
    if (trimmed.length > COMMENT_MAX_LENGTH) {
      setError(`Комментарий слишком длинный (максимум ${COMMENT_MAX_LENGTH} символов).`)
      return
    }
    setSaving(true)
    setError(null)
    try {
      await createRequestComment(requestId, trimmed)
      message.success('Комментарий сохранён')
      setBody('')
      await loadComments()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Не удалось сохранить комментарий')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="tg-create-page">
      <Card className="tg-create-card" bordered>
        <Typography.Title level={4}>
          {isRequestValid ? `Комментарии к заявке #${requestId}` : 'Комментарии к заявке'}
        </Typography.Title>
        {!isRequestValid ? (
          <Typography.Paragraph type="warning">
            Идентификатор заявки не определён.
          </Typography.Paragraph>
        ) : null}

        {listError ? <Alert type="error" showIcon message={listError} style={{ marginBottom: 12 }} /> : null}

        {loadingComments ? (
          <div style={{ textAlign: 'center', padding: '16px 0' }}>
            <Spin />
          </div>
        ) : comments.length === 0 ? (
          isRequestValid ? <Empty description="Пока нет комментариев" /> : null
        ) : (
          <List
            dataSource={comments}
            renderItem={(item) => (
              <List.Item key={item.id}>
                <List.Item.Meta
                  title={
                    <span>
                      <Typography.Text strong>{item.created_by_full_name || 'Пользователь'}</Typography.Text>
                      <Typography.Text type="secondary" style={{ marginLeft: 8, fontWeight: 400 }}>
                        {formatDateTime(item.created_at)}
                      </Typography.Text>
                    </span>
                  }
                  description={
                    <Typography.Paragraph style={{ whiteSpace: 'pre-wrap', marginBottom: 0 }}>
                      {item.body}
                    </Typography.Paragraph>
                  }
                />
              </List.Item>
            )}
          />
        )}
      </Card>

      <Card className="tg-create-card" bordered style={{ marginTop: 12 }}>
        {error ? <Alert type="error" showIcon message={error} style={{ marginBottom: 12 }} /> : null}

        <Typography.Text strong>Новый комментарий</Typography.Text>
        <div style={{ height: 8 }} />
        <Input.TextArea
          ref={textareaRef as React.RefObject<HTMLTextAreaElement>}
          rows={5}
          value={body}
          maxLength={COMMENT_MAX_LENGTH}
          showCount
          onChange={(e) => setBody(e.target.value)}
          placeholder="Напишите комментарий..."
        />
      </Card>

      <div className="tg-sticky-actions">
        <Button
          type="primary"
          block
          onClick={() => void submit()}
          loading={saving}
          disabled={!body.trim() || !isRequestValid}
        >
          Отправить комментарий
        </Button>
      </div>
    </div>
  )
}
