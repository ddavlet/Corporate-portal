import { useEffect, useState } from 'react'
import { Button, Card, Input, Space, Typography, message } from 'antd'
import { createRequestComment } from '../../lib/api'
import type { RequestComment } from '../../lib/api'

const COMMENT_MAX_LENGTH = 4000
const EXCERPT_CHAR_THRESHOLD = 180

function formatCommentDate(value: string): string {
  if (!value) return ''
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return ''
  return new Intl.DateTimeFormat('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    timeZone: 'Asia/Tashkent',
  }).format(d)
}

function isLong(body: string): boolean {
  return body.length > EXCERPT_CHAR_THRESHOLD || body.includes('\n')
}

function CommentCard({ comment }: { comment: RequestComment }) {
  const [expanded, setExpanded] = useState(false)
  const long = isLong(comment.body)

  return (
    <Card size="small" style={{ marginBottom: 8 }}>
      <Space direction="vertical" size={4} style={{ display: 'flex' }}>
        <Space wrap style={{ justifyContent: 'space-between', width: '100%' }}>
          <Typography.Text strong>{comment.created_by_full_name}</Typography.Text>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {formatCommentDate(comment.created_at)}
          </Typography.Text>
        </Space>
        <Typography.Text
          style={
            !expanded && long
              ? {
                  display: '-webkit-box',
                  WebkitLineClamp: 3,
                  WebkitBoxOrient: 'vertical',
                  overflow: 'hidden',
                  whiteSpace: 'pre-wrap',
                }
              : { whiteSpace: 'pre-wrap' }
          }
        >
          {comment.body}
        </Typography.Text>
        {long ? (
          <Button
            type="link"
            size="small"
            style={{ padding: 0, height: 'auto' }}
            onClick={() => setExpanded((v) => !v)}
          >
            {expanded ? 'Свернуть' : 'Показать полностью'}
          </Button>
        ) : null}
      </Space>
    </Card>
  )
}

type Props = {
  requestId: number
  comments: RequestComment[]
  onCommentAdded: () => Promise<void>
  variant?: 'default' | 'telegram'
}

export function RequestCommentsSection({ requestId, comments, onCommentAdded, variant = 'default' }: Props) {
  const [localComments, setLocalComments] = useState<RequestComment[]>(comments)
  const [formOpen, setFormOpen] = useState(false)
  const [body, setBody] = useState('')
  const [saving, setSaving] = useState(false)

  const isTg = variant === 'telegram'

  // Sync when parent re-fetches (e.g. page refresh)
  useEffect(() => {
    setLocalComments(comments)
  }, [comments])

  const openForm = () => {
    setFormOpen(true)
  }

  const cancel = () => {
    setFormOpen(false)
    setBody('')
  }

  const submit = async () => {
    const trimmed = body.trim()
    if (!trimmed) {
      message.warning('Введите текст комментария')
      return
    }
    setSaving(true)
    try {
      const created = await createRequestComment(requestId, trimmed)
      setLocalComments((prev) => [created, ...prev])
      setFormOpen(false)
      setBody('')
      await onCommentAdded()
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : 'Не удалось сохранить комментарий')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div id="request-comments-section">
      <Space style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }} align="center">
        <Typography.Text strong>
          Комментарии{localComments.length > 0 ? ` (${localComments.length})` : ''}
        </Typography.Text>
        {!formOpen ? (
          <Button size={isTg ? 'large' : 'small'} onClick={openForm}>
            + Добавить
          </Button>
        ) : null}
      </Space>

      {formOpen ? (
        <Card size="small" style={{ marginBottom: 8 }}>
          <Space direction="vertical" size={8} style={{ display: 'flex' }}>
            <Input.TextArea
              autoFocus
              rows={3}
              value={body}
              maxLength={COMMENT_MAX_LENGTH}
              showCount
              onChange={(e) => setBody(e.target.value)}
              placeholder="Напишите комментарий..."
            />
            <Space>
              <Button type="primary" size="small" loading={saving} onClick={() => void submit()}>
                Отправить
              </Button>
              <Button size="small" onClick={cancel}>
                Отмена
              </Button>
            </Space>
          </Space>
        </Card>
      ) : null}

      {localComments.length === 0 && !formOpen ? (
        <Typography.Text type="secondary">Нет комментариев</Typography.Text>
      ) : (
        localComments.map((c) => <CommentCard key={c.id} comment={c} />)
      )}
    </div>
  )
}
