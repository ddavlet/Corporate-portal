import { useEffect, useMemo, useState } from 'react'
import { Button, Divider, Input, Select, Space, message } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { createEmployee, listEmployees, type EmployeeDto } from '../../lib/api'

export function EmployeeSelect({
  value,
  onChange,
  excludeIds = [],
  knownEmployees = [],
}: {
  value?: number
  onChange?: (id: number) => void
  excludeIds?: number[]
  knownEmployees?: EmployeeDto[]
}) {
  const [items, setItems] = useState<EmployeeDto[]>(knownEmployees)
  const [newName, setNewName] = useState('')
  const [creating, setCreating] = useState(false)

  useEffect(() => {
    let cancelled = false
    listEmployees()
      .then((rows) => {
        if (!cancelled) setItems(rows)
      })
      .catch((e: unknown) => message.error(e instanceof Error ? e.message : 'Не удалось загрузить сотрудников'))
    return () => {
      cancelled = true
    }
  }, [])

  const options = useMemo(
    () =>
      items
        .filter((e) => e.id === value || !excludeIds.includes(e.id))
        .map((e) => ({ value: e.id, label: e.full_name })),
    [items, excludeIds, value],
  )

  const onCreate = async () => {
    const name = newName.trim()
    if (!name) return
    setCreating(true)
    try {
      const created = await createEmployee(name)
      setItems((prev) => (prev.some((e) => e.id === created.id) ? prev : [...prev, created]))
      setNewName('')
      onChange?.(created.id)
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : 'Не удалось добавить сотрудника')
    } finally {
      setCreating(false)
    }
  }

  return (
    <Select
      showSearch
      placeholder="Сотрудник"
      optionFilterProp="label"
      style={{ width: 280 }}
      value={value}
      onChange={(id: number) => onChange?.(id)}
      options={options}
      dropdownRender={(menu) => (
        <>
          {menu}
          <Divider style={{ margin: '8px 0' }} />
          <Space style={{ padding: '0 8px 4px' }}>
            <Input
              placeholder="ФИО нового сотрудника"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => e.stopPropagation()}
            />
            <Button type="text" icon={<PlusOutlined />} loading={creating} onClick={() => void onCreate()}>
              Добавить
            </Button>
          </Space>
        </>
      )}
    />
  )
}
