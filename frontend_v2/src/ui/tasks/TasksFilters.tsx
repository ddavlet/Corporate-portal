import { Button, Select, Space } from 'antd'
import type { TaskStatus, TaskSourceType } from './types'
import type { AssigneeCandidate } from '../../lib/tasksApi'

export interface FiltersState {
  status?: TaskStatus
  source_type?: TaskSourceType
  assignee?: number
}

const STATUS_OPTIONS = [
  { value: 'new', label: 'Новые' },
  { value: 'in_progress', label: 'В работе' },
  { value: 'done', label: 'Выполнено' },
]

const SOURCE_OPTIONS = [
  { value: 'manual', label: 'Вручную' },
  { value: 'approval_step', label: 'Согласование' },
  { value: 'request_approved', label: 'Оплата' },
  { value: 'payment_verify', label: 'Проверка' },
  { value: 'request_rejected', label: 'Отказ' },
  { value: 'escalation', label: 'Эскалация' },
]

interface Props {
  filters: FiltersState
  onChange: (f: FiltersState) => void
  candidates: AssigneeCandidate[]
  showAssigneeFilter: boolean
}

export function TasksFilters({ filters, onChange, candidates, showAssigneeFilter }: Props) {
  const hasFilters = !!(filters.status ?? filters.source_type ?? filters.assignee)

  return (
    <Space wrap size={8} style={{ marginBottom: 12 }}>
      <Select
        allowClear
        placeholder="Статус"
        style={{ width: 150 }}
        value={filters.status ?? null}
        options={STATUS_OPTIONS}
        onChange={(v: TaskStatus | null) =>
          onChange({ ...filters, status: v ?? undefined })
        }
      />
      <Select
        allowClear
        placeholder="Тип задачи"
        style={{ width: 175 }}
        value={filters.source_type ?? null}
        options={SOURCE_OPTIONS}
        onChange={(v: TaskSourceType | null) =>
          onChange({ ...filters, source_type: v ?? undefined })
        }
      />
      {showAssigneeFilter && (
        <Select
          allowClear
          showSearch
          placeholder="Исполнитель"
          style={{ width: 185 }}
          value={filters.assignee ?? null}
          optionFilterProp="label"
          options={candidates.map((c) => ({ value: c.id, label: c.username }))}
          onChange={(v: number | null) =>
            onChange({ ...filters, assignee: v ?? undefined })
          }
        />
      )}
      {hasFilters && (
        <Button size="small" onClick={() => onChange({})}>
          Сбросить
        </Button>
      )}
    </Space>
  )
}
