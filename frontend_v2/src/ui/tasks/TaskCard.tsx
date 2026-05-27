import { Badge, Button, Popconfirm, Space, Tag, Typography } from 'antd'
import { BellOutlined, CheckOutlined, CommentOutlined, DeleteOutlined } from '@ant-design/icons'
import type { Task, TaskSourceType } from './types'

const SOURCE_LABEL: Record<TaskSourceType, string> = {
  manual: 'Вручную',
  approval_step: 'Согласование',
  request_approved: 'Оплата',
  payment_verify: 'Проверка',
  request_rejected: 'Отказ',
  escalation: 'Эскалация',
}

const SOURCE_COLOR: Record<TaskSourceType, string> = {
  manual: 'default',
  approval_step: 'blue',
  request_approved: 'green',
  payment_verify: 'cyan',
  request_rejected: 'orange',
  escalation: 'red',
}

interface TaskCardProps {
  task: Task
  onClick: () => void
  showAssignee?: boolean
  isDragOverlay?: boolean
  currentUserId?: number | null
  isAdminOrDirector?: boolean
  onArchive?: (id: number) => void
  onDelete?: (id: number) => void
  onRemind?: (id: number) => void
}

function formatCardDate(task: Task): string {
  const raw = task.status === 'done' && task.completed_at ? task.completed_at : task.created_at
  return new Date(raw).toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: '2-digit' })
}

export function TaskCard({
  task,
  onClick,
  showAssignee,
  isDragOverlay,
  currentUserId,
  isAdminOrDirector,
  onArchive,
  onDelete,
  onRemind,
}: TaskCardProps) {
  const label = SOURCE_LABEL[task.source_type] ?? task.source_type
  const color = SOURCE_COLOR[task.source_type] ?? 'default'
  const dateStr = formatCardDate(task)

  // Archive (move-to-done) maps to backend CanChangeStatus: assignee OR admin/director.
  const canArchive =
    !isDragOverlay &&
    task.status !== 'done' &&
    onArchive != null &&
    (isAdminOrDirector || (currentUserId != null && task.assignee?.id === currentUserId))

  const canDelete =
    !isDragOverlay &&
    onDelete != null &&
    (isAdminOrDirector || (currentUserId != null && task.created_by_id === currentUserId))

  // Remind only makes sense when assignee is someone other than the current user.
  const canRemind =
    !isDragOverlay &&
    task.status !== 'done' &&
    isAdminOrDirector &&
    onRemind != null &&
    task.assignee?.id != null &&
    task.assignee.id !== currentUserId

  const hasActions = canArchive || canDelete || canRemind

  const stopAndCall = (e: React.MouseEvent, fn: () => void) => {
    e.stopPropagation()
    fn()
  }

  // Prevent dnd-kit from picking up pointer events on action buttons.
  const stopPointer = (e: React.PointerEvent) => e.stopPropagation()

  return (
    <div
      onClick={isDragOverlay ? undefined : onClick}
      style={{
        background: '#fff',
        borderRadius: 6,
        padding: '10px 12px',
        marginBottom: 8,
        boxShadow: isDragOverlay ? '0 4px 12px rgba(0,0,0,.18)' : '0 1px 3px rgba(0,0,0,.08)',
        cursor: isDragOverlay ? 'grabbing' : 'pointer',
        borderLeft: task.has_unseen_admin_comment ? '3px solid #1677ff' : '3px solid transparent',
        transition: 'box-shadow .15s',
        rotate: isDragOverlay ? '2deg' : undefined,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 6 }}>
        <Typography.Text strong style={{ fontSize: 13, flex: 1, wordBreak: 'break-word' }}>
          {task.title}
        </Typography.Text>
        {task.has_unseen_admin_comment && (
          <Badge count={<CommentOutlined style={{ color: '#1677ff', fontSize: 14 }} />} />
        )}
      </div>
      <div style={{ marginTop: 6, display: 'flex', flexWrap: 'wrap', gap: 4, alignItems: 'center' }}>
        <Tag color={color} style={{ margin: 0, fontSize: 11 }}>{label}</Tag>
        {showAssignee && task.assignee && (
          <Typography.Text type="secondary" style={{ fontSize: 11 }}>
            {task.assignee.username}
          </Typography.Text>
        )}
        {task.source_request_id && (
          <Typography.Text type="secondary" style={{ fontSize: 11 }}>
            #{task.source_request_id}
          </Typography.Text>
        )}
        <Typography.Text type="secondary" style={{ fontSize: 11, marginLeft: 'auto' }}>
          {dateStr}
        </Typography.Text>
      </div>

      {hasActions && (
        <div style={{ marginTop: 8, display: 'flex', justifyContent: 'flex-end' }}>
          <Space size={4}>
            {canArchive && (
              <Button
                size="small"
                type="text"
                icon={<CheckOutlined />}
                title="Выполнено"
                style={{ color: '#52c41a', padding: '0 4px', height: 22 }}
                onPointerDown={stopPointer}
                onClick={(e) => stopAndCall(e, () => onArchive!(task.id))}
              />
            )}
            {canRemind && (
              <Button
                size="small"
                type="text"
                icon={<BellOutlined />}
                title="Напомнить исполнителю"
                style={{ color: '#faad14', padding: '0 4px', height: 22 }}
                onPointerDown={stopPointer}
                onClick={(e) => stopAndCall(e, () => onRemind!(task.id))}
              />
            )}
            {canDelete && (
              <Popconfirm
                title="Удалить задачу?"
                description="Действие необратимо."
                okText="Удалить"
                okButtonProps={{ danger: true }}
                cancelText="Отмена"
                onConfirm={(e) => {
                  e?.stopPropagation()
                  onDelete!(task.id)
                }}
                onCancel={(e) => e?.stopPropagation()}
              >
                <Button
                  size="small"
                  type="text"
                  icon={<DeleteOutlined />}
                  title="Удалить задачу"
                  danger
                  style={{ padding: '0 4px', height: 22 }}
                  onPointerDown={stopPointer}
                  onClick={(e) => e.stopPropagation()}
                />
              </Popconfirm>
            )}
          </Space>
        </div>
      )}
    </div>
  )
}
