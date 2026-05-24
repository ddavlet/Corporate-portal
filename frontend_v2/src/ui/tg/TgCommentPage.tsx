import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Card, Input, Typography, message } from 'antd'
import { useSearchParams } from 'react-router-dom'
import { createRequestComment } from '../../lib/api'
import { resolveCommentRequestId } from './tgCommentRequestId'

const COMMENT_MAX_LENGTH = 4000

export function TgCommentPage() {
  const [searchParams] = useSearchParams()
  const [body, setBody] = useState('')
  const [saving, setSaving] = useState(false)
  const [done, setDone] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [requestId, setRequestId] = useState(0)
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
      setDone(true)
      window.setTimeout(() => {
        window.Telegram?.WebApp?.close?.()
      }, 800)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Не удалось сохранить комментарий')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="tg-create-page">
      <Card className="tg-create-card" bordered>
        <Typography.Title level={4}>Комментарий к заявке</Typography.Title>
        {isRequestValid ? (
          <Typography.Paragraph type="secondary">
            Заявка #{requestId}
          </Typography.Paragraph>
        ) : (
          <Typography.Paragraph type="warning">
            Идентификатор заявки не определён.
          </Typography.Paragraph>
        )}

        {error ? <Alert type="error" showIcon message={error} style={{ marginBottom: 12 }} /> : null}
        {done ? <Alert type="success" showIcon message="Комментарий сохранён" style={{ marginBottom: 12 }} /> : null}

        <Typography.Text strong>Комментарий</Typography.Text>
        <div style={{ height: 8 }} />
        <Input.TextArea
          ref={textareaRef as React.RefObject<HTMLTextAreaElement>}
          rows={5}
          value={body}
          maxLength={COMMENT_MAX_LENGTH}
          showCount
          onChange={(e) => setBody(e.target.value)}
          placeholder="Напишите комментарий..."
          disabled={done}
          autoFocus
        />
      </Card>

      <div className="tg-sticky-actions">
        <Button
          type="primary"
          block
          onClick={() => void submit()}
          loading={saving}
          disabled={done || !body.trim()}
        >
          Отправить комментарий
        </Button>
      </div>
    </div>
  )
}
