import { useState } from 'react'
import { Alert, Button, Empty, Input, Modal, Space, Typography } from 'antd'
import { askAiQuestion } from '../../lib/api'

type ChatMessage = {
  role: 'user' | 'ai'
  text: string
}

type Props = {
  open: boolean
  onClose: () => void
}

export function AiQuestionsModal({ open, onClose }: Props) {
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [question, setQuestion] = useState('')
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const reset = () => {
    setSessionId(null)
    setQuestion('')
    setMessages([])
    setError(null)
  }

  const handleClose = () => {
    reset()
    onClose()
  }

  const onAsk = async () => {
    const normalized = question.trim()
    if (!normalized) return
    setSending(true)
    setError(null)
    try {
      setMessages((prev) => [...prev, { role: 'user', text: normalized }])
      const response = await askAiQuestion({
        question: normalized,
        session_id: sessionId ?? undefined,
      })
      setSessionId(response.session_id)
      setMessages((prev) => [...prev, { role: 'ai', text: response.reponse }])
      setQuestion('')
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Не удалось получить ответ ИИ')
    } finally {
      setSending(false)
    }
  }

  return (
    <Modal title="Вопросы в ИИ" open={open} onCancel={handleClose} footer={null} destroyOnClose width={700}>
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        <Typography.Text type="secondary">
          Задайте вопрос. История хранится только в рамках текущей сессии на стороне n8n.
        </Typography.Text>

        <div style={{ maxHeight: 360, overflowY: 'auto', border: '1px solid #f0f0f0', borderRadius: 8, padding: 12 }}>
          {messages.length === 0 ? (
            <Empty description="Пока нет сообщений" image={Empty.PRESENTED_IMAGE_SIMPLE} />
          ) : (
            <Space direction="vertical" size="middle" style={{ width: '100%' }}>
              {messages.map((item, idx) => (
                <div key={`${item.role}-${idx}`}>
                  <Typography.Text strong>{item.role === 'user' ? 'Вы' : 'ИИ'}</Typography.Text>
                  <Typography.Paragraph style={{ marginBottom: 0, marginTop: 4, whiteSpace: 'pre-wrap' }}>
                    {item.text}
                  </Typography.Paragraph>
                </div>
              ))}
            </Space>
          )}
        </div>

        {error ? <Alert type="error" message={error} showIcon /> : null}

        <Input.TextArea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Введите вопрос..."
          autoSize={{ minRows: 3, maxRows: 8 }}
          disabled={sending}
        />

        <Space>
          <Button type="primary" onClick={() => void onAsk()} loading={sending} disabled={!question.trim()}>
            Отправить
          </Button>
          <Button onClick={handleClose}>Закрыть</Button>
        </Space>
      </Space>
    </Modal>
  )
}
