import { useEffect, useState } from 'react'
import { Alert, Button, Empty, Input, List, Modal, Segmented, Space, Spin, Tabs, Tag, Typography, message } from 'antd'
import type { FeedbackKind, FeedbackWorkStatus, MyFeedbackItem } from '../../lib/api'
import { listMyFeedback, refineFeedbackWithAi, submitFeedback } from '../../lib/api'

type Props = {
  open: boolean
  onClose: () => void
  pagePath: string
}

const KIND_OPTIONS: { label: string; value: FeedbackKind }[] = [
  { label: 'Ошибка', value: 'error' },
  { label: 'Улучшение', value: 'improvement' },
]

const KIND_LABELS: Record<FeedbackKind, string> = {
  error: 'Ошибка',
  improvement: 'Улучшение',
}

const WORK_STATUS_COLORS: Record<FeedbackWorkStatus, string> = {
  new: 'red',
  in_progress: 'blue',
  done: 'green',
}

function formatDate(iso: string): string {
  try {
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return iso
    return d.toLocaleString('ru-RU', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return iso
  }
}

export function FeedbackModal({ open, onClose, pagePath }: Props) {
  const [activeTab, setActiveTab] = useState<'submit' | 'my'>('submit')
  const [kind, setKind] = useState<FeedbackKind>('error')
  const [text, setText] = useState('')
  const [hasRefinedOnce, setHasRefinedOnce] = useState(false)
  const [refining, setRefining] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [myItems, setMyItems] = useState<MyFeedbackItem[]>([])
  const [myLoading, setMyLoading] = useState(false)
  const [myError, setMyError] = useState<string | null>(null)

  const reset = () => {
    setKind('error')
    setText('')
    setHasRefinedOnce(false)
    setError(null)
    setActiveTab('submit')
  }

  const handleClose = () => {
    reset()
    onClose()
  }

  useEffect(() => {
    if (!open || activeTab !== 'my') return
    let cancelled = false
    setMyLoading(true)
    setMyError(null)
    void (async () => {
      try {
        const items = await listMyFeedback()
        if (!cancelled) setMyItems(items)
      } catch (e: unknown) {
        if (!cancelled) setMyError(e instanceof Error ? e.message : 'Не удалось загрузить обращения')
      } finally {
        if (!cancelled) setMyLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [open, activeTab])

  const onRefine = async () => {
    if (!kind || !text.trim()) return
    setRefining(true)
    setError(null)
    try {
      const { feedback } = await refineFeedbackWithAi({ kind, text: text.trim() })
      setText(feedback)
      setHasRefinedOnce(true)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Не удалось сформировать текст')
      setHasRefinedOnce(true)
    } finally {
      setRefining(false)
    }
  }

  const onSubmit = async () => {
    if (!kind || !text.trim()) return
    setSubmitting(true)
    setError(null)
    try {
      let body = text.trim()
      if (!hasRefinedOnce) {
        try {
          const { feedback } = await refineFeedbackWithAi({ kind, text: body })
          body = feedback
          setText(feedback)
          setHasRefinedOnce(true)
        } catch {
          // AI refine failed — proceed with original text
        }
      }
      const result = await submitFeedback({
        kind,
        body,
        page_path: pagePath,
      })
      if (result.delivery.status === 'failed') {
        message.warning(result.delivery.error || 'Сообщение сохранено, но Telegram не отправился.')
      } else {
        message.success('Спасибо, отзыв отправлен.')
      }
      handleClose()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Не удалось отправить')
    } finally {
      setSubmitting(false)
    }
  }

  const canRefine = Boolean(kind && text.trim())
  const canSubmit = Boolean(kind && text.trim())

  const submitTab = (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Typography.Text type="secondary">
        Опишите ситуацию своими словами. При желании нажмите «Сформировать» — мы прогоним текст через ИИ, чтобы он
        был структурным и понятным. Затем нажмите «Отправить».
      </Typography.Text>

      <div>
        <Typography.Text strong>Тип</Typography.Text>
        <div style={{ marginTop: 8 }}>
          <Segmented<FeedbackKind>
            options={KIND_OPTIONS}
            value={kind}
            onChange={(v) => {
              setKind(v)
              setHasRefinedOnce(false)
            }}
            block
          />
        </div>
      </div>

      <div>
        <Typography.Text strong>Ваш комментарий</Typography.Text>
        <Typography.Paragraph type="secondary" style={{ marginBottom: 8, marginTop: 4 }}>
          {kind === 'error'
            ? 'Укажите: что делали, что ожидали, что произошло вместо этого, страница или раздел. По возможности — шаги, чтобы повторить.'
            : 'Опишите задачу или боль, как сейчас устроено, и каким вы видите улучшение (процесс, интерфейс, отчёт).'}
        </Typography.Paragraph>
        <Input.TextArea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Текст комментария…"
          autoSize={{ minRows: 6, maxRows: 14 }}
        />
      </div>

      {error ? <Alert type="error" message={error} showIcon /> : null}

      <Space wrap>
        <Button onClick={() => void onRefine()} loading={refining} disabled={!canRefine}>
          Сформировать
        </Button>
        <Button type="primary" onClick={() => void onSubmit()} loading={submitting} disabled={!canSubmit}>
          Отправить
        </Button>
        <Button onClick={handleClose}>Отмена</Button>
      </Space>
    </Space>
  )

  const myTab = (
    <div>
      {myLoading ? (
        <div style={{ textAlign: 'center', padding: 24 }}>
          <Spin />
        </div>
      ) : myError ? (
        <Alert type="error" message={myError} showIcon />
      ) : myItems.length === 0 ? (
        <Empty description="У вас пока нет обращений" />
      ) : (
        <List
          dataSource={myItems}
          renderItem={(item) => (
            <List.Item key={item.id}>
              <List.Item.Meta
                title={
                  <Space size="small" wrap>
                    <Tag color={WORK_STATUS_COLORS[item.work_status]}>{item.work_status_label}</Tag>
                    <Tag>{KIND_LABELS[item.kind]}</Tag>
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      {formatDate(item.created_at)}
                    </Typography.Text>
                  </Space>
                }
                description={
                  <div>
                    <Typography.Paragraph
                      style={{ marginBottom: 4, whiteSpace: 'pre-wrap' }}
                      ellipsis={{ rows: 4, expandable: true, symbol: 'показать полностью' }}
                    >
                      {item.body}
                    </Typography.Paragraph>
                    {item.page_path ? (
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                        {item.page_path}
                      </Typography.Text>
                    ) : null}
                  </div>
                }
              />
            </List.Item>
          )}
        />
      )}
    </div>
  )

  return (
    <Modal
      title="Обратная связь"
      open={open}
      onCancel={handleClose}
      footer={null}
      destroyOnClose
      width={620}
    >
      <Tabs
        activeKey={activeTab}
        onChange={(k) => setActiveTab(k as 'submit' | 'my')}
        items={[
          { key: 'submit', label: 'Отправить', children: submitTab },
          { key: 'my', label: 'Мои обращения', children: myTab },
        ]}
      />
    </Modal>
  )
}
