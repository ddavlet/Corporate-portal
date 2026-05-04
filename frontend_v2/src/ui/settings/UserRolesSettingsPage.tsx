import { useCallback, useEffect, useMemo, useState } from 'react'
import { Alert, Button, Card, Select, Space, Table, Typography, message } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  getAccessMatrix,
  getSettingsAccess,
  updateAccessMatrixAssignments,
  type AccessMatrixUserRow,
} from '../../lib/api'

/** Совпадает с `TenantUserRole` на бекенде. */
const TENANT_ROLE_OPTIONS: Array<{ value: string; label: string }> = [
  { value: 'admin', label: 'Администратор компании' },
  { value: 'director', label: 'Директор' },
  { value: 'approver', label: 'Согласующий' },
  { value: 'requester', label: 'Заявитель' },
  { value: 'cashier', label: 'Кассир' },
  { value: 'accountant', label: 'Бухгалтер' },
  { value: 'investor', label: 'Инвестор' },
]

type RowData = AccessMatrixUserRow & { key: number }

function sortedRolesCopy(roles: string[]): string[] {
  return [...roles].sort()
}

function rolesEqual(a: string[], b: string[]): boolean {
  const x = sortedRolesCopy(a)
  const y = sortedRolesCopy(b)
  return x.length === y.length && x.every((v, i) => v === y[i])
}

export function UserRolesSettingsPage() {
  const [gateLoading, setGateLoading] = useState(true)
  const [allowed, setAllowed] = useState(false)
  const [gateError, setGateError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [users, setUsers] = useState<AccessMatrixUserRow[]>([])
  const [draftRoles, setDraftRoles] = useState<Record<number, string[]>>({})

  const loadMatrix = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await getAccessMatrix()
      setUsers(data.users)
      const dr: Record<number, string[]> = {}
      for (const u of data.users) dr[u.user_id] = [...u.roles]
      setDraftRoles(dr)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Не удалось загрузить пользователей')
      setUsers([])
      setDraftRoles({})
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    void (async () => {
      setGateLoading(true)
      setGateError(null)
      try {
        const access = await getSettingsAccess()
        if (cancelled) return
        setAllowed(Boolean(access.can_manage_tenant_settings))
      } catch (e: unknown) {
        if (cancelled) return
        setGateError(e instanceof Error ? e.message : 'Не удалось проверить доступ')
        setAllowed(false)
      } finally {
        if (!cancelled) setGateLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (!allowed) return
    void loadMatrix()
  }, [allowed, loadMatrix])

  const isDirty = useMemo(
    () => users.some((u) => !rolesEqual(draftRoles[u.user_id] ?? [], u.roles)),
    [users, draftRoles],
  )

  const dataSource: RowData[] = useMemo(
    () => users.map((u) => ({ ...u, key: u.user_id })),
    [users],
  )

  const onSave = async () => {
    if (!users.length) return
    const assignments = users.map((u) => ({
      user_id: u.user_id,
      roles: draftRoles[u.user_id] ?? u.roles,
    }))
    if (assignments.some((a) => a.roles.length === 0)) {
      message.warning('У каждого участника должна быть хотя бы одна роль.')
      return
    }
    setSaving(true)
    setError(null)
    try {
      const data = await updateAccessMatrixAssignments(assignments)
      setUsers(data.users)
      const dr: Record<number, string[]> = {}
      for (const u of data.users) dr[u.user_id] = [...u.roles]
      setDraftRoles(dr)
      message.success('Роли сохранены')
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Не удалось сохранить роли')
    } finally {
      setSaving(false)
    }
  }

  const columns: ColumnsType<RowData> = [
    { title: 'ID', dataIndex: 'user_id', width: 72 },
    { title: 'Логин', dataIndex: 'username', width: 160 },
    {
      title: 'ФИО',
      dataIndex: 'full_name',
      width: 200,
      render: (v: string) => v || '—',
    },
    {
      title: 'Роли',
      key: 'roles',
      render: (_, row) => (
        <Select
          mode="multiple"
          allowClear={false}
          style={{ minWidth: 280, maxWidth: '100%' }}
          placeholder="Выберите роли"
          options={TENANT_ROLE_OPTIONS}
          value={draftRoles[row.user_id] ?? row.roles}
          onChange={(vals) =>
            setDraftRoles((prev) => ({
              ...prev,
              [row.user_id]: [...vals],
            }))
          }
          optionFilterProp="label"
        />
      ),
    },
  ]

  return (
    <Space direction="vertical" size={12} style={{ display: 'flex' }}>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        Настройки пользователей
      </Typography.Title>
      <Typography.Paragraph type="secondary">
        Роли определяют доступ к модулям портала для пользователей с активным подключением к компании
        (участники tenant). Редактирование доступно только администратору компании.
      </Typography.Paragraph>
      <Alert
        type="info"
        showIcon
        message="Ограничения"
        description="Должен остаться хотя бы один пользователь с ролью «Администратор компании» (admin). Пользователей без активного членства в компании здесь нельзя изменить."
      />
      {gateLoading ? (
        <Card loading />
      ) : gateError ? (
        <Alert type="error" showIcon message={gateError} />
      ) : !allowed ? (
        <Alert
          type="warning"
          showIcon
          message="Доступ только для администратора компании"
          description="Управление ролями доступно только пользователям с ролью admin в этом tenant."
        />
      ) : null}
      {error ? <Alert type="error" showIcon message={error} /> : null}
      {allowed ? (
        <Card>
          <Space style={{ marginBottom: 12 }}>
            <Button onClick={() => void loadMatrix()} disabled={saving}>
              Обновить
            </Button>
            <Button type="primary" onClick={() => void onSave()} loading={saving} disabled={!isDirty}>
              Сохранить изменения
            </Button>
          </Space>
          <Table<RowData>
            loading={loading}
            columns={columns}
            dataSource={dataSource}
            pagination={{ pageSize: 20, showSizeChanger: true }}
            scroll={{ x: 720 }}
          />
        </Card>
      ) : null}
    </Space>
  )
}
