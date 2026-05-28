import { useEffect, useRef, useState } from 'react'
import {
  Button,
  Descriptions,
  Divider,
  Input,
  Modal,
  Popconfirm,
  Skeleton,
  Space,
  Tag,
  Typography,
  message,
} from 'antd'
import { BellOutlined, DeleteOutlined, EditOutlined } from '@ant-design/icons'
import { addTaskComment, changeTaskStatus, deleteTask, getTask, patchTask, remindTask } from '../../lib/tasksApi'
import type { TaskDetail, TaskComment, TaskStatus } from './types'

const STATUS_LABEL: Record<TaskStatus, string> = {
  new: 'Новая',
  in_progress: 'В работе',
  done: 'Выполнена',
}

const STATUS_COLOR: Record<TaskStatus, string> = {
  new: 'blue',
  in_progress: 'orange',
  done: 'green',
}

const NEXT_STATUSES: Record<TaskStatus, { status: TaskStatus; label: string; type: 'primary' | 'default' | 'dashed' }[]> = {
  new: [
    { status: 'in_progress', label: 'Взять в работу', type: 'primary' },
    { status: 'done', label: 'Завершить', type: 'default' },
  ],
  in_progress: [
    { status: 'done', label: 'Завершить', type: 'primary' },
    { status: 'new', label: 'Вернуть', type: 'dashed' },
  ],
  done: [],
}

function formatDt(value: string | null | undefined): string {
  if (!value) return '—'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return '—'
  return new Intl.DateTimeFormat('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    timeZone: 'Asia/Tashkent',
  }).format(d)
}

function CommentCard({ comment }: { comment: TaskComment }) {
  return (
    <div
      style={{
        background: comment.is_admin_comment ? '#e6f4ff' : '#fafafa',
        border: `1px solid ${comment.is_admin_comment ? '#91caff' : '#e8e8e8'}`,
        borderRadius: 6,
        padding: '8px 12px',
        marginBottom: 8,
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
        <Space size={6}>
          <Typography.Text strong style={{ fontSize: 13 }}>
            {comment.author?.username ?? 'Система'}
          </Typography.Text>
          {comment.is_admin_comment && (
            <Tag color="blue" style={{ margin: 0, fontSize: 11 }}>Менеджер</Tag>
          )}
        </Space>
        <Typography.Text type="secondary" style={{ fontSize: 11 }}>
          {formatDt(comment.created_at)}
        </Typography.Text>
      </div>
      <Typography.Text style={{ whiteSpace: 'pre-wrap', fontSize: 13 }}>
        {comment.body}
      </Typography.Text>
    </div>
  )
}

interface Props {
  taskId: number
  onClose: () => void
  currentUserId?: number | null
  isAdminOrDirector?: boolean
}

export function TaskDetailModal({ taskId, onClose, currentUserId, isAdminOrDirector }: Props) {
  const [task, setTask] = useState<TaskDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [statusChanging, setStatusChanging] = useState(false)
  const [commentBody, setCommentBody] = useState('')
  const [commentSaving, setCommentSaving] = useState(false)
  const [commentFormOpen, setCommentFormOpen] = useState(false)
  const [editing, setEditing] = useState(false)
  const [editTitle, setEditTitle] = useState('')
  const [editDescription, setEditDescription] = useState('')
  const [editSaving, setEditSaving] = useState(false)
  const [reminding, setReminding] = useState(false)
  const [deleting, setDeleting] = useState(false)

  // Keep a stable ref so the fetch effect never re-runs due to onClose identity changes.
  const onCloseRef = useRef(onClose)
  useEffect(() => { onCloseRef.current = onClose })

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    void (async () => {
      try {
        const data = await getTask(taskId)
        if (!cancelled) setTask(data)
      } catch (err) {
        void message.error(err instanceof Error ? err.message : 'Ошибка загрузки задачи')
        if (!cancelled) onCloseRef.current()
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [taskId])

  const handleStatusChange = async (newStatus: TaskStatus) => {
    if (!task) return
    setStatusChanging(true)
    try {
      const updated = await changeTaskStatus(task.id, newStatus)
      setTask(updated)
    } catch (err) {
      void message.error(err instanceof Error ? err.message : 'Не удалось изменить статус')
    } finally {
      setStatusChanging(false)
    }
  }

  const handleCommentSubmit = async () => {
    const trimmed = commentBody.trim()
    if (!trimmed) {
      void message.warning('Введите текст комментария')
      return
    }
    if (!task) return
    setCommentSaving(true)
    try {
      const created = await addTaskComment(task.id, trimmed)
      setTask((prev) =>
        prev ? { ...prev, comments: [...prev.comments, created] } : prev,
      )
      setCommentBody('')
      setCommentFormOpen(false)
    } catch (err) {
      void message.error(err instanceof Error ? err.message : 'Не удалось сохранить комментарий')
    } finally {
      setCommentSaving(false)
    }
  }

  const handleStartEdit = () => {
    if (!task) return
    setEditTitle(task.title)
    setEditDescription(task.description ?? '')
    setEditing(true)
  }

  const handleCancelEdit = () => {
    setEditing(false)
    setEditTitle('')
    setEditDescription('')
  }

  const handleSaveEdit = async () => {
    if (!task) return
    const title = editTitle.trim()
    if (!title) {
      void message.warning('Введите название задачи')
      return
    }
    setEditSaving(true)
    try {
      const updated = await patchTask(task.id, {
        title,
        description: editDescription.trim(),
      })
      setTask(updated)
      setEditing(false)
      void message.success('Задача сохранена')
    } catch (err) {
      void message.error(err instanceof Error ? err.message : 'Не удалось сохранить задачу')
    } finally {
      setEditSaving(false)
    }
  }

  const handleRemind = async () => {
    if (!task) return
    setReminding(true)
    try {
      await remindTask(task.id)
      void message.success('Напоминание отправлено')
    } catch (err) {
      void message.error(err instanceof Error ? err.message : 'Не удалось отправить напоминание')
    } finally {
      setReminding(false)
    }
  }

  const handleDelete = async () => {
    if (!task) return
    setDeleting(true)
    try {
      await deleteTask(task.id)
      void message.success('Задача удалена')
      onClose()
    } catch (err) {
      void message.error(err instanceof Error ? err.message : 'Не удалось удалить задачу')
      setDeleting(false)
    }
  }

  const canEdit =
    task != null &&
    (isAdminOrDirector ||
      (currentUserId != null && task.created_by?.id === currentUserId))

  const canDelete =
    task != null &&
    (isAdminOrDirector ||
      (currentUserId != null && task.created_by?.id === currentUserId))

  const canRemind =
    task != null &&
    task.status !== 'done' &&
    !!isAdminOrDirector &&
    task.assignee?.id != null &&
    task.assignee.id !== currentUserId

  const nextOptions = task ? (NEXT_STATUSES[task.status] ?? []) : []

  return (
    <Modal
      open
      title={
        loading || !task
          ? 'Задача'
          : `Задача #${task.id}`
      }
      onCancel={onClose}
      footer={null}
      width={640}
      destroyOnHidden
    >
      {loading && <Skeleton active paragraph={{ rows: 6 }} />}

      {!loading && task && (
        <>
          <Space style={{ marginBottom: 12 }} wrap>
            <Tag color={STATUS_COLOR[task.status]} style={{ fontSize: 13, padding: '2px 10px' }}>
              {STATUS_LABEL[task.status]}
            </Tag>
            {nextOptions.map(({ status, label, type }) => (
              <Button
                key={status}
                size="small"
                type={type}
                loading={statusChanging}
                onClick={() => void handleStatusChange(status)}
              >
                {label}
              </Button>
            ))}
          </Space>

          {editing ? (
            <div style={{ marginBottom: 16 }}>
              <Input
                value={editTitle}
                onChange={(e) => setEditTitle(e.target.value)}
                maxLength={255}
                placeholder="Название задачи"
                style={{ marginBottom: 8, fontSize: 15, fontWeight: 600 }}
              />
              <Input.TextArea
                value={editDescription}
                onChange={(e) => setEditDescription(e.target.value)}
                rows={3}
                maxLength={4000}
                showCount
                placeholder="Описание (необязательно)"
                style={{ marginBottom: 8 }}
              />
              <Space>
                <Button type="primary" size="small" loading={editSaving} onClick={() => void handleSaveEdit()}>
                  Сохранить
                </Button>
                <Button size="small" onClick={handleCancelEdit} disabled={editSaving}>
                  Отмена
                </Button>
              </Space>
            </div>
          ) : (
            <>
              <div style={{ display: 'flex', alignItems: 'flex-start', gap: 4, marginBottom: 8 }}>
                <Typography.Title level={5} style={{ margin: 0, flex: 1 }}>
                  {task.title}
                </Typography.Title>
                {canRemind && (
                  <Button
                    size="small"
                    type="text"
                    icon={<BellOutlined />}
                    title="Напомнить исполнителю"
                    loading={reminding}
                    style={{ color: '#faad14' }}
                    onClick={() => void handleRemind()}
                  />
                )}
                {canEdit && (
                  <Button
                    size="small"
                    type="text"
                    icon={<EditOutlined />}
                    title="Редактировать"
                    onClick={handleStartEdit}
                  />
                )}
                {canDelete && (
                  <Popconfirm
                    title="Удалить задачу?"
                    description="Действие необратимо."
                    okText="Удалить"
                    okButtonProps={{ danger: true, loading: deleting }}
                    cancelText="Отмена"
                    onConfirm={() => void handleDelete()}
                  >
                    <Button
                      size="small"
                      type="text"
                      danger
                      icon={<DeleteOutlined />}
                      title="Удалить задачу"
                    />
                  </Popconfirm>
                )}
              </div>
              {task.description && (
                <Typography.Paragraph
                  style={{ whiteSpace: 'pre-wrap', color: '#595959', marginBottom: 16 }}
                >
                  {task.description}
                </Typography.Paragraph>
              )}
            </>
          )}

          <Descriptions size="small" column={1} bordered style={{ marginBottom: 16 }}>
            <Descriptions.Item label="Исполнитель">
              {task.assignee?.username ?? '—'}
            </Descriptions.Item>
            {task.created_by && (
              <Descriptions.Item label="Создал">
                {task.created_by.username}
              </Descriptions.Item>
            )}
            {task.source_request_id && (
              <Descriptions.Item label="Заявка">
                #{task.source_request_id}
              </Descriptions.Item>
            )}
            <Descriptions.Item label="Создана">
              {formatDt(task.created_at)}
            </Descriptions.Item>
            {task.completed_at && (
              <Descriptions.Item label="Завершена">
                {formatDt(task.completed_at)}
              </Descriptions.Item>
            )}
          </Descriptions>

          <Divider style={{ margin: '12px 0' }} />

          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
            <Typography.Text strong>
              Комментарии{task.comments.length > 0 ? ` (${task.comments.length})` : ''}
            </Typography.Text>
            {!commentFormOpen && (
              <Button size="small" onClick={() => setCommentFormOpen(true)}>
                + Добавить
              </Button>
            )}
          </div>

          {commentFormOpen && (
            <div style={{ marginBottom: 12 }}>
              <Input.TextArea
                autoFocus
                rows={3}
                value={commentBody}
                maxLength={4000}
                showCount
                onChange={(e) => setCommentBody(e.target.value)}
                placeholder="Напишите комментарий..."
                style={{ marginBottom: 8 }}
              />
              <Space>
                <Button
                  type="primary"
                  size="small"
                  loading={commentSaving}
                  onClick={() => void handleCommentSubmit()}
                >
                  Отправить
                </Button>
                <Button
                  size="small"
                  onClick={() => { setCommentFormOpen(false); setCommentBody('') }}
                >
                  Отмена
                </Button>
              </Space>
            </div>
          )}

          {task.comments.length === 0 && !commentFormOpen ? (
            <Typography.Text type="secondary" style={{ fontSize: 13 }}>
              Нет комментариев
            </Typography.Text>
          ) : (
            task.comments.map((c) => <CommentCard key={c.id} comment={c} />)
          )}
        </>
      )}
    </Modal>
  )
}
