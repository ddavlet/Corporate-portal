import { FormEvent, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Alert, Button, Card, Form, Input, Space, Typography } from 'antd'
import { LockOutlined, UserOutlined } from '@ant-design/icons'
import { useAuth } from './auth'

export function LoginPage() {
  const navigate = useNavigate()
  const { login } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      const res = await fetch('/api/auth/token/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ username, password }),
      })
      if (!res.ok) {
        const t = await res.text().catch(() => '')
        throw new Error(t || `Ошибка входа (${res.status})`)
      }
      const data = (await res.json()) as { access: string; refresh: string }
      login({ tokens: { access: data.access, refresh: data.refresh }, username })
      navigate('/', { replace: true })
    } catch (err: any) {
      setError(err?.message || 'Не удалось выполнить вход')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="login-page">
      <Card style={{ width: 420 }}>
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          <Typography.Title level={3} style={{ margin: 0 }}>
            Вход в систему
          </Typography.Title>
          <Typography.Text type="secondary">
            Тенант определяется автоматически по текущему домену. Все запросы идут в <span className="mono">/api/*</span>.
          </Typography.Text>

          <Form layout="vertical" onSubmitCapture={onSubmit}>
            <Form.Item label="Логин" required>
              <Input
                prefix={<UserOutlined />}
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
              />
            </Form.Item>
            <Form.Item label="Пароль" required>
              <Input.Password
                prefix={<LockOutlined />}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
              />
            </Form.Item>

            {error ? <Alert type="error" showIcon message="Ошибка входа" description={error} style={{ marginBottom: 12 }} /> : null}

            <Button type="primary" htmlType="submit" loading={loading} block disabled={!username || !password}>
              Войти
            </Button>
          </Form>
        </Space>
      </Card>
    </div>
  )
}

