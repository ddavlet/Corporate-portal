import { Alert, Button, Card, Checkbox, Radio, Result, Skeleton, Space, Typography } from 'antd'
import { useEffect, useState } from 'react'
import { notifyApiSuccess } from '../../lib/apiNotify'
import { getReportTemplates, updateReportTemplates, type ReportTemplateInfo } from '../../lib/reportsApi'
import { useTenantAdmin } from '../../lib/useTenantAdmin'

export function ReportTemplateSettingsPage() {
  const { isAdmin, loading: adminLoading } = useTenantAdmin()
  const [available, setAvailable] = useState<ReportTemplateInfo[] | null>(null)
  const [allowed, setAllowed] = useState<string[]>([])
  const [defaultKey, setDefaultKey] = useState('classic')
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    let active = true
    getReportTemplates()
      .then((data) => {
        if (!active) return
        setAvailable(data.available)
        setAllowed(data.allowed.map((template) => template.key))
        setDefaultKey(data.default)
      })
      .catch((e: unknown) => {
        if (active) setError(e instanceof Error ? e.message : 'Не удалось загрузить шаблоны')
      })
    return () => {
      active = false
    }
  }, [])

  const toggle = (key: string, checked: boolean) => {
    const next = checked ? [...allowed, key] : allowed.filter((item) => item !== key)
    setAllowed(next)
    if (!next.includes(defaultKey) && next.length > 0) setDefaultKey(next[0])
  }

  const save = async () => {
    setSaving(true)
    setError(null)
    try {
      const data = await updateReportTemplates({ default_template: defaultKey, allowed_templates: allowed })
      setAllowed(data.allowed.map((template) => template.key))
      setDefaultKey(data.default)
      notifyApiSuccess('Шаблоны отчётов сохранены')
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Не удалось сохранить')
    } finally {
      setSaving(false)
    }
  }

  if (adminLoading) return <Skeleton active />
  if (!isAdmin) return <Result status="403" title="Нет доступа" subTitle="Шаблоны отчётов меняет администратор компании." />
  if (!available && !error) return <Skeleton active />

  return (
    <Card title="Шаблоны отчётов">
      <Space direction="vertical" size="large" style={{ width: '100%' }}>
        <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
          Какие виды страницы «Отчёты» доступны сотрудникам компании и какой открывается по умолчанию. Сотрудник может
          переключаться между разрешёнными видами.
        </Typography.Paragraph>
        {error ? <Alert type="error" showIcon message={error} /> : null}
        {available ? (
          <>
            <div>
              <Typography.Text strong>Разрешённые шаблоны</Typography.Text>
              <Space direction="vertical" style={{ display: 'flex', marginTop: 8 }}>
                {available.map((template) => (
                  <Checkbox key={template.key} checked={allowed.includes(template.key)} onChange={(event) => toggle(template.key, event.target.checked)}>
                    <Typography.Text strong>{template.label}</Typography.Text>
                    <Typography.Text type="secondary">{` — ${template.description}`}</Typography.Text>
                  </Checkbox>
                ))}
              </Space>
            </div>
            <div>
              <Typography.Text strong>Шаблон по умолчанию</Typography.Text>
              <Radio.Group
                style={{ display: 'block', marginTop: 8 }}
                value={defaultKey}
                onChange={(event) => setDefaultKey(event.target.value)}
                options={available.filter((template) => allowed.includes(template.key)).map((template) => ({ label: template.label, value: template.key }))}
              />
            </div>
            <div>
              <Button type="primary" loading={saving} disabled={allowed.length === 0} onClick={() => void save()}>
                Сохранить
              </Button>
            </div>
          </>
        ) : null}
      </Space>
    </Card>
  )
}
