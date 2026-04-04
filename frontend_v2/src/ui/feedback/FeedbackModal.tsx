import { useState } from 'react'
import { Alert, Button, Input, Modal, Segmented, Space, Typography, message } from 'antd'
import type { FeedbackKind } from '../../lib/api'
import { refineFeedbackWithAi, submitFeedback } from '../../lib/api'

type Props = {
  open: boolean
  onClose: () => void
  pagePath: string
}

const KIND_OPTIONS: { label: string; value: FeedbackKind }[] = [
  { label: 'Ошибка', value: 'error' },
  { label: 'Улучшение', value: 'improvement' },
]

export function FeedbackModal({ open, onClose, pagePath }: Props) {
  const [kind, setKind] = useState<FeedbackKind | undefined>(undefined)
  const [text, setText] = useState('')
  const [hasRefinedOnce, setHasRefinedOnce] = useState(false)
  const [refining, setRefining] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const reset = () => {
    setKind(undefined)
    setText('')
    setHasRefinedOnce(false)
    setError(null)
  }

  const handleClose = () => {
    reset()
    onClose()
  }

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
    } finally {
      setRefining(false)
    }
  }

  const onSubmit = async () => {
    if (!kind || !text.trim() || !hasRefinedOnce) return
    setSubmitting(true)
    setError(null)
    try {
      const result = await submitFeedback({
        kind,
        body: text.trim(),
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
  const canSubmit = Boolean(kind && text.trim() && hasRefinedOnce)

  return (
    <Modal
      title="Обратная связь"
      open={open}
      onCancel={handleClose}
      footer={null}
      destroyOnClose
      width={560}
    >
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        <Typography.Text type="secondary">
          Сначала опишите ситуацию своими словами, затем нажмите «Сформировать» — мы прогоним текст через ИИ, чтобы он
          был структурным и понятным. При необходимости отредактируйте результат и снова нажмите «Сформировать».
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
              : kind === 'improvement'
                ? 'Опишите задачу или боль, как сейчас устроено, и каким вы видите улучшение (процесс, интерфейс, отчёт).'
                : 'Выберите тип отзыва — появятся подсказки для текста.'}
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
    </Modal>
  )
}
