import { useCallback, useEffect, useRef, useState } from 'react'
import { Alert, Button, Card, Grid, Segmented, Spin, Typography, message } from 'antd'
import { HistoryOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons'
import {
  DndContext,
  DragOverlay,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from '@dnd-kit/core'
import { useDroppable } from '@dnd-kit/core'
import { useDraggable } from '@dnd-kit/core'
import { CSS } from '@dnd-kit/utilities'
import { getSettingsAccess } from '../../lib/api'
import { changeTaskStatus, getTaskDashboard, listAssigneeCandidates, listTasks } from '../../lib/tasksApi'
import type { AssigneeCandidate } from '../../lib/tasksApi'
import type { Task, TaskDashboard, TaskStatus } from './types'
import { TaskCard } from './TaskCard'
import { TaskCreateModal } from './TaskCreateModal'
import { TaskDetailModal } from './TaskDetailModal'
import { TasksFilters } from './TasksFilters'
import type { FiltersState } from './TasksFilters'

const POLL_MS = 30_000

const ALLOWED_DROP: Record<TaskStatus, TaskStatus[]> = {
  new: ['in_progress', 'done'],
  in_progress: ['new', 'done'],
  done: [],
}

interface BoardData {
  new: Task[]
  in_progress: Task[]
  done_recent: Task[]
  isDashboard: boolean
}

function groupByStatus(tasks: Task[]): Omit<BoardData, 'isDashboard'> {
  const board = { new: [] as Task[], in_progress: [] as Task[], done_recent: [] as Task[] }
  for (const t of tasks) {
    if (t.status === 'new') board.new.push(t)
    else if (t.status === 'in_progress') board.in_progress.push(t)
    else if (t.status === 'done') board.done_recent.push(t)
  }
  return board
}

function dashboardToBoard(d: TaskDashboard): Omit<BoardData, 'isDashboard'> {
  return { new: d.new, in_progress: d.in_progress, done_recent: d.done_recent }
}

function hasAnyFilter(f: FiltersState): boolean {
  return !!(f.status ?? f.source_type ?? f.assignee)
}

function moveTaskBetweenColumns(
  board: BoardData,
  taskId: number,
  fromStatus: TaskStatus,
  toStatus: TaskStatus,
): BoardData {
  const fromKey = fromStatus === 'done' ? 'done_recent' : fromStatus
  const toKey = toStatus === 'done' ? 'done_recent' : toStatus
  const task = (board[fromKey] as Task[]).find((t) => t.id === taskId)
  if (!task) return board
  // Optimistic: also set completed_at when moving to done so the date line on the
  // card matches the new status. The next poll reconciles with the server.
  const updated: Task = {
    ...task,
    status: toStatus,
    completed_at:
      toStatus === 'done'
        ? new Date().toISOString()
        : null,
  }
  // Insert in sorted position so the card doesn't jump on the next poll.
  // Done column sorts by completed_at desc; other columns sort by created_at desc.
  const inserted = [...(board[toKey] as Task[]), updated]
  if (toKey === 'done_recent') {
    inserted.sort((a, b) => {
      const ad = a.completed_at ? Date.parse(a.completed_at) : 0
      const bd = b.completed_at ? Date.parse(b.completed_at) : 0
      return bd - ad
    })
  } else {
    inserted.sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))
  }
  return {
    ...board,
    [fromKey]: (board[fromKey] as Task[]).filter((t) => t.id !== taskId),
    [toKey]: inserted,
  }
}

export function TasksPage() {
  const [board, setBoard] = useState<BoardData | null>(null)
  const [loading, setLoading] = useState(true)
  const [isWideScope, setIsWideScope] = useState(false)
  const [showAll, setShowAll] = useState(true)
  const [filters, setFilters] = useState<FiltersState>({})
  const [candidates, setCandidates] = useState<AssigneeCandidate[]>([])
  const [selectedTaskId, setSelectedTaskId] = useState<number | null>(null)
  const [createOpen, setCreateOpen] = useState(false)
  const [draggingTask, setDraggingTask] = useState<Task | null>(null)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const screens = Grid.useBreakpoint()
  const isMobile = !screens.md

  const showAssignee = isWideScope && showAll

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } }),
  )

  const fetchBoard = useCallback(
    async (
      wide: boolean,
      all: boolean,
      currentFilters: FiltersState,
      silent = false,
    ) => {
      if (!silent) setLoading(true)
      try {
        const useListTasks = (wide && all) || hasAnyFilter(currentFilters)
        if (useListTasks) {
          const params = {
            status: currentFilters.status,
            source_type: currentFilters.source_type,
            assignee: currentFilters.assignee,
            include_all_done: currentFilters.status === 'done' ? true : undefined,
          }
          const tasks = await listTasks(params)
          setBoard({ ...groupByStatus(tasks), isDashboard: false })
        } else {
          const dashboard = await getTaskDashboard()
          setBoard({ ...dashboardToBoard(dashboard), isDashboard: true })
        }
      } catch (err) {
        if (!silent)
          void message.error(err instanceof Error ? err.message : 'Ошибка загрузки задач')
      } finally {
        if (!silent) setLoading(false)
      }
    },
    [],
  )

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const [access, cands] = await Promise.all([
          getSettingsAccess(),
          listAssigneeCandidates(),
        ])
        const wide = access.roles.includes('admin') || access.roles.includes('director')
        if (!cancelled) {
          setIsWideScope(wide)
          setCandidates(cands)
          await fetchBoard(wide, true, {})
        }
      } catch {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [fetchBoard])

  // Keep refs of the latest scope/filters so the polling interval can read them
  // without being torn down and recreated on every user interaction.
  const pollArgsRef = useRef({ isWideScope, showAll, filters })
  useEffect(() => {
    pollArgsRef.current = { isWideScope, showAll, filters }
  })

  useEffect(() => {
    intervalRef.current = setInterval(() => {
      const { isWideScope: w, showAll: a, filters: f } = pollArgsRef.current
      void fetchBoard(w, a, f, true)
    }, POLL_MS)
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current)
    }
  }, [fetchBoard])

  const handleScopeChange = (all: boolean) => {
    setShowAll(all)
    // Switching to "mine" mode resets filters — keeping filters in mine mode would
    // still send listTasks (hasAnyFilter=true) which uses TenantTasksScope server-side,
    // returning all tenant tasks instead of just the admin's own tasks.
    const nextFilters = all ? filters : {}
    if (!all) setFilters({})
    void fetchBoard(isWideScope, all, nextFilters)
  }

  const handleFiltersChange = (next: FiltersState) => {
    setFilters(next)
    void fetchBoard(isWideScope, showAll, next)
  }

  const handleRefresh = () => {
    void fetchBoard(isWideScope, showAll, filters)
  }

  const handleDragStart = (event: DragStartEvent) => {
    const { active } = event
    const taskId = active.data.current?.taskId as number | undefined
    const status = active.data.current?.status as TaskStatus | undefined
    if (!board || taskId == null || !status) return
    const colKey = status === 'done' ? 'done_recent' : status
    const task = (board[colKey] as Task[]).find((t) => t.id === taskId) ?? null
    setDraggingTask(task)
  }

  const handleDragEnd = (event: DragEndEvent) => {
    setDraggingTask(null)
    const { active, over } = event
    if (!over || !board) return

    const taskId = active.data.current?.taskId as number | undefined
    const fromStatus = active.data.current?.status as TaskStatus | undefined
    const toStatus = over.data.current?.columnStatus as TaskStatus | undefined

    if (taskId == null || !fromStatus || !toStatus || fromStatus === toStatus) return
    if (!ALLOWED_DROP[fromStatus].includes(toStatus)) return

    // Optimistic update
    setBoard((prev) => prev ? moveTaskBetweenColumns(prev, taskId, fromStatus, toStatus) : prev)

    void changeTaskStatus(taskId, toStatus).catch((err) => {
      void message.error(err instanceof Error ? err.message : 'Не удалось изменить статус')
      void fetchBoard(isWideScope, showAll, filters, true)
    })
  }

  const isArchiveMode = filters.status === 'done'
  const isDashboardMode = board?.isDashboard ?? false
  const doneCaptionExtra = isDashboardMode ? 'последние 3' : undefined

  if (loading && !board) return <Spin style={{ display: 'block', marginTop: 80 }} />

  return (
    <div style={{ padding: isMobile ? '12px' : '16px 24px' }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: 12,
          flexWrap: 'wrap',
          gap: 8,
        }}
      >
        <Typography.Title level={4} style={{ margin: 0 }}>
          Задачи
        </Typography.Title>

        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          {isWideScope && (
            <Segmented
              value={showAll ? 'all' : 'mine'}
              options={[
                { label: 'Все задачи', value: 'all' },
                { label: 'Мои задачи', value: 'mine' },
              ]}
              onChange={(v) => handleScopeChange(v === 'all')}
            />
          )}
          <Button icon={<ReloadOutlined />} onClick={handleRefresh} loading={loading} />
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => setCreateOpen(true)}
          >
            Новая задача
          </Button>
        </div>
      </div>

      <TasksFilters
        filters={filters}
        onChange={handleFiltersChange}
        candidates={candidates}
        showAssigneeFilter={showAssignee}
      />

      {isArchiveMode && (
        <Alert
          type="info"
          showIcon
          icon={<HistoryOutlined />}
          message="Архив выполненных задач"
          description="Показаны все выполненные задачи. Нажмите «Сбросить» в фильтрах, чтобы вернуться к доске."
          style={{ marginBottom: 12 }}
        />
      )}

      <DndContext sensors={sensors} onDragStart={handleDragStart} onDragEnd={handleDragEnd}>
        <div
          style={{
            display: 'flex',
            flexDirection: isMobile ? 'column' : 'row',
            gap: 16,
            alignItems: 'flex-start',
            overflowX: isMobile ? 'visible' : 'auto',
            paddingBottom: 8,
          }}
        >
          <DroppableBoardColumn
            columnStatus="new"
            title="Новые"
            accentColor="#1677ff"
            tasks={board?.new ?? []}
            showAssignee={showAssignee}
            onTaskClick={setSelectedTaskId}
            draggingTaskId={draggingTask?.id ?? null}
            isMobile={isMobile}
          />
          <DroppableBoardColumn
            columnStatus="in_progress"
            title="В работе"
            accentColor="#faad14"
            tasks={board?.in_progress ?? []}
            showAssignee={showAssignee}
            onTaskClick={setSelectedTaskId}
            draggingTaskId={draggingTask?.id ?? null}
            isMobile={isMobile}
          />
          <DroppableBoardColumn
            columnStatus="done"
            title={isArchiveMode ? 'Архив' : 'Выполнено'}
            accentColor="#52c41a"
            tasks={board?.done_recent ?? []}
            showAssignee={showAssignee}
            onTaskClick={setSelectedTaskId}
            caption={doneCaptionExtra}
            draggingTaskId={draggingTask?.id ?? null}
            isMobile={isMobile}
            onViewArchive={
              isDashboardMode && !isArchiveMode
                ? () => handleFiltersChange({ status: 'done' })
                : undefined
            }
          />
        </div>

        <DragOverlay>
          {draggingTask ? (
            <TaskCard
              task={draggingTask}
              showAssignee={showAssignee}
              onClick={() => undefined}
              isDragOverlay
            />
          ) : null}
        </DragOverlay>
      </DndContext>

      {selectedTaskId != null && (
        <TaskDetailModal
          taskId={selectedTaskId}
          onClose={() => {
            setSelectedTaskId(null)
            void fetchBoard(isWideScope, showAll, filters, true)
          }}
        />
      )}

      {createOpen && (
        <TaskCreateModal
          onClose={(created) => {
            setCreateOpen(false)
            if (created) void fetchBoard(isWideScope, showAll, filters, true)
          }}
        />
      )}
    </div>
  )
}

interface DroppableBoardColumnProps {
  columnStatus: TaskStatus
  title: string
  accentColor: string
  tasks: Task[]
  showAssignee: boolean
  onTaskClick: (id: number) => void
  caption?: string
  onViewArchive?: () => void
  draggingTaskId: number | null
  isMobile: boolean
}

function DroppableBoardColumn({
  columnStatus,
  title,
  accentColor,
  tasks,
  showAssignee,
  onTaskClick,
  caption,
  onViewArchive,
  draggingTaskId,
  isMobile,
}: DroppableBoardColumnProps) {
  const { setNodeRef, isOver } = useDroppable({
    id: `column-${columnStatus}`,
    data: { columnStatus },
    // DnD is disabled on mobile (stacked layout) and on the terminal "done" column.
    disabled: isMobile || columnStatus === 'done',
  })

  return (
    <Card
      size="small"
      style={{
        flex: isMobile ? 'none' : '1 1 280px',
        width: isMobile ? '100%' : undefined,
        minWidth: isMobile ? 0 : 260,
        background: isOver ? '#e6f7ff' : '#f5f7fa',
        transition: 'background 0.15s',
      }}
      styles={{ body: { padding: '8px 8px 4px' } }}
      title={
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span
            style={{
              display: 'inline-block',
              width: 10,
              height: 10,
              borderRadius: '50%',
              background: accentColor,
              flexShrink: 0,
            }}
          />
          <span style={{ fontWeight: 600, fontSize: 13 }}>{title}</span>
          <span style={{ fontWeight: 400, color: '#888', fontSize: 12 }}>
            ({tasks.length}
            {caption ? ` · ${caption}` : ''})
          </span>
        </div>
      }
    >
      <div ref={setNodeRef} style={{ minHeight: 40 }}>
        {tasks.length === 0 ? (
          <Typography.Text
            type="secondary"
            style={{ fontSize: 12, padding: '8px 4px', display: 'block' }}
          >
            {columnStatus === 'new' && 'Нет новых задач'}
            {columnStatus === 'in_progress' && 'Задач в работе нет'}
            {columnStatus === 'done' && 'Нет выполненных задач'}
          </Typography.Text>
        ) : (
          tasks.map((t) => (
            <DraggableTaskCard
              key={t.id}
              task={t}
              showAssignee={showAssignee}
              onClick={() => onTaskClick(t.id)}
              isDragging={draggingTaskId === t.id}
              dndDisabled={isMobile}
            />
          ))
        )}
      </div>

      {onViewArchive && (
        <div style={{ textAlign: 'center', paddingTop: 4, paddingBottom: 4 }}>
          <Button
            type="link"
            size="small"
            icon={<HistoryOutlined />}
            onClick={onViewArchive}
            style={{ fontSize: 12, color: '#888' }}
          >
            Смотреть архив
          </Button>
        </div>
      )}
    </Card>
  )
}

interface DraggableTaskCardProps {
  task: Task
  showAssignee: boolean
  onClick: () => void
  isDragging: boolean
  dndDisabled: boolean
}

function DraggableTaskCard({ task, showAssignee, onClick, isDragging, dndDisabled }: DraggableTaskCardProps) {
  const { attributes, listeners, setNodeRef, transform } = useDraggable({
    id: `task-${task.id}`,
    data: { taskId: task.id, status: task.status },
    disabled: dndDisabled || task.status === 'done',
  })

  const style: React.CSSProperties = {
    transform: CSS.Translate.toString(transform),
    opacity: isDragging ? 0.35 : 1,
    cursor: dndDisabled || task.status === 'done' ? 'pointer' : 'grab',
    // Only block native touch gestures when DnD is actually enabled; otherwise the
    // user can't scroll a column by touching a card (a real issue on mobile).
    touchAction: dndDisabled ? 'auto' : 'none',
  }

  return (
    <div ref={setNodeRef} style={style} {...listeners} {...attributes}>
      <TaskCard task={task} showAssignee={showAssignee} onClick={onClick} />
    </div>
  )
}
