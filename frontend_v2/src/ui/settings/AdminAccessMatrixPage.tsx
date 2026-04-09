import { useEffect, useMemo, useState } from 'react'
import { Alert, Card, Space, Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { getAccessMatrix, type AccessMatrixUserRow } from '../../lib/api'

type MatrixRow = {
  key: number
  user_id: number
  username: string
  full_name: string
  roles: string[]
  tenant_settings_access: boolean
  module_access: Record<string, boolean>
}

export function AdminAccessMatrixPage() {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [rows, setRows] = useState<AccessMatrixUserRow[]>([])
  const [modules, setModules] = useState<Array<{ module_key: string; display_name: string }>>([])

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setLoading(true)
      setError(null)
      try {
        const data = await getAccessMatrix()
        if (cancelled) return
        setRows(data.users)
        setModules(data.modules)
      } catch (e: unknown) {
        if (cancelled) return
        setError(e instanceof Error ? e.message : 'Не удалось загрузить матрицу доступов')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const tableData: MatrixRow[] = useMemo(
    () =>
      rows.map((r) => ({
        key: r.user_id,
        ...r,
      })),
    [rows],
  )

  const columns: ColumnsType<MatrixRow> = useMemo(() => {
    const base: ColumnsType<MatrixRow> = [
      { title: 'User ID', dataIndex: 'user_id', width: 90 },
      { title: 'Username', dataIndex: 'username', width: 180 },
      { title: 'ФИО', dataIndex: 'full_name', width: 220, render: (v: string) => v || '—' },
      {
        title: 'Роли',
        dataIndex: 'roles',
        width: 260,
        render: (roles: string[]) =>
          roles?.length ? (
            <Space size={[4, 4]} wrap>
              {roles.map((role) => (
                <Tag key={role}>{role}</Tag>
              ))}
            </Space>
          ) : (
            '—'
          ),
      },
      {
        title: 'Tenant настройки',
        dataIndex: 'tenant_settings_access',
        width: 150,
        render: (v: boolean) => (v ? <Tag color="green">Да</Tag> : <Tag>Нет</Tag>),
      },
    ]

    const moduleCols: ColumnsType<MatrixRow> = modules.map((m) => ({
      title: m.display_name,
      key: `mod_${m.module_key}`,
      width: 140,
      render: (_, row) => (row.module_access?.[m.module_key] ? <Tag color="green">Да</Tag> : <Tag>Нет</Tag>),
    }))
    return [...base, ...moduleCols]
  }, [modules])

  return (
    <div style={{ maxWidth: 1400 }}>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        Админка: матрица доступов
      </Typography.Title>
      <Typography.Paragraph type="secondary">
        Список пользователей тенанта, их роли и эффективный доступ по модулям.
      </Typography.Paragraph>
      {error ? <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} /> : null}
      <Card>
        <Table<MatrixRow>
          loading={loading}
          columns={columns}
          dataSource={tableData}
          pagination={{ pageSize: 20, showSizeChanger: true }}
          scroll={{ x: 1200 }}
        />
      </Card>
    </div>
  )
}
