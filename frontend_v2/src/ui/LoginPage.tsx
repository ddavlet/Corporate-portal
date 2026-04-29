import { FormEvent, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Alert, Button, Card, Form, Input, Segmented, Space, Typography } from 'antd'
import { LockOutlined, UserOutlined } from '@ant-design/icons'
import { useAuth } from './auth'
import { exchangeTelegramLoginWidget, getTelegramLoginWidgetConfig, type TelegramLoginWidgetAuthData } from '../lib/api'

export function LoginPage() {
  const navigate = useNavigate()
  const { login } = useAuth()
  const [mode, setMode] = useState<'password' | 'otp' | 'telegram'>('password')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [otpCode, setOtpCode] = useState('')
  const [otpRequested, setOtpRequested] = useState(false)
  const [otpInfo, setOtpInfo] = useState<string | null>(null)
  const [telegramBotUsername, setTelegramBotUsername] = useState('')
  const [telegramConfigLoaded, setTelegramConfigLoaded] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const tgWidgetRef = useRef<HTMLDivElement | null>(null)

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
      navigate('/requests', { replace: true })
    } catch (err: any) {
      setError(err?.message || 'Не удалось выполнить вход')
    } finally {
      setLoading(false)
    }
  }

  async function onRequestOtp(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setOtpInfo(null)
    setLoading(true)
    try {
      const res = await fetch('/api/auth/otp/request/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ username }),
      })
      const payload = await res.json().catch(() => null)
      if (!res.ok) {
        throw new Error((payload && payload.detail) || `Ошибка запроса OTP (${res.status})`)
      }
      setOtpRequested(true)
      setOtpInfo((payload && payload.detail) || 'Код отправлен.')
    } catch (err: any) {
      setError(err?.message || 'Не удалось запросить OTP')
    } finally {
      setLoading(false)
    }
  }

  async function onVerifyOtp(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      const res = await fetch('/api/auth/otp/verify/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ username, code: otpCode }),
      })
      const payload = await res.json().catch(() => null)
      if (!res.ok) {
        throw new Error((payload && payload.detail) || `Ошибка проверки OTP (${res.status})`)
      }
      login({ tokens: { access: payload.access, refresh: payload.refresh }, username })
      navigate('/requests', { replace: true })
    } catch (err: any) {
      setError(err?.message || 'Не удалось выполнить вход по OTP')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    let disposed = false
    void (async () => {
      try {
        const cfg = await getTelegramLoginWidgetConfig()
        if (!disposed) {
          setTelegramBotUsername(cfg.bot_username || '')
          setTelegramConfigLoaded(true)
        }
      } catch {
        if (!disposed) {
          setTelegramConfigLoaded(true)
        }
      }
    })()
    return () => {
      disposed = true
    }
  }, [])

  useEffect(() => {
    if (mode !== 'telegram') return
    if (!telegramBotUsername) return
    const container = tgWidgetRef.current
    if (!container) return
    container.innerHTML = ''

    window.onTelegramAuth = async (user: TelegramLoginWidgetAuthData) => {
      setError(null)
      setLoading(true)
      try {
        const payload = await exchangeTelegramLoginWidget(user)
        login({ tokens: { access: payload.access, refresh: payload.refresh }, username: payload.username })
        navigate('/requests', { replace: true })
      } catch (err: any) {
        setError(err?.message || 'Не удалось выполнить вход через Telegram')
      } finally {
        setLoading(false)
      }
    }

    const script = document.createElement('script')
    script.src = 'https://telegram.org/js/telegram-widget.js?22'
    script.async = true
    script.setAttribute('data-telegram-login', telegramBotUsername)
    script.setAttribute('data-size', 'large')
    script.setAttribute('data-userpic', 'false')
    script.setAttribute('data-request-access', 'write')
    script.setAttribute('data-onauth', 'onTelegramAuth(user)')
    container.appendChild(script)

    return () => {
      if (window.onTelegramAuth) delete window.onTelegramAuth
      container.innerHTML = ''
    }
  }, [mode, telegramBotUsername, login, navigate])

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
          <Segmented
            block
            value={mode}
            options={[
              { label: 'Пароль', value: 'password' },
              { label: 'OTP в Telegram', value: 'otp' },
              { label: 'Telegram Widget', value: 'telegram' },
            ]}
            onChange={(value) => {
              setMode(value as 'password' | 'otp' | 'telegram')
              setError(null)
              setOtpInfo(null)
              setOtpRequested(false)
              setOtpCode('')
            }}
          />

          {mode === 'password' ? (
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
          ) : mode === 'otp' ? (
            <Form layout="vertical" onSubmitCapture={otpRequested ? onVerifyOtp : onRequestOtp}>
              <Form.Item label="Логин" required>
                <Input
                  prefix={<UserOutlined />}
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  autoComplete="username"
                />
              </Form.Item>

              {otpRequested ? (
                <Form.Item label="Код из Telegram" required>
                  <Input
                    value={otpCode}
                    onChange={(e) => setOtpCode(e.target.value)}
                    autoComplete="one-time-code"
                  />
                </Form.Item>
              ) : null}

              {otpInfo ? <Alert type="info" showIcon message={otpInfo} style={{ marginBottom: 12 }} /> : null}
              {error ? <Alert type="error" showIcon message="Ошибка OTP" description={error} style={{ marginBottom: 12 }} /> : null}

              {otpRequested ? (
                <Space direction="vertical" style={{ width: '100%' }}>
                  <Button type="primary" htmlType="submit" loading={loading} block disabled={!username || !otpCode}>
                    Подтвердить и войти
                  </Button>
                  <Button
                    htmlType="button"
                    block
                    onClick={() => {
                      setOtpRequested(false)
                      setOtpCode('')
                      setOtpInfo(null)
                    }}
                  >
                    Запросить код заново
                  </Button>
                </Space>
              ) : (
                <Button type="primary" htmlType="submit" loading={loading} block disabled={!username}>
                  Получить OTP
                </Button>
              )}
            </Form>
          ) : (
            <Space direction="vertical" style={{ width: '100%' }}>
              {!telegramConfigLoaded ? <Typography.Text type="secondary">Загрузка настроек Telegram...</Typography.Text> : null}
              {telegramConfigLoaded && !telegramBotUsername ? (
                <Alert
                  type="warning"
                  showIcon
                  message="Telegram Login Widget не настроен"
                  description="Укажите username бота в настройках тенанта."
                />
              ) : null}
              {telegramBotUsername ? (
                <>
                  <Typography.Text type="secondary">
                    Вход через Telegram-аккаунт, связанный с пользователем в этой организации.
                  </Typography.Text>
                  <div ref={tgWidgetRef} />
                </>
              ) : null}
              {error ? <Alert type="error" showIcon message="Ошибка Telegram входа" description={error} /> : null}
            </Space>
          )}
        </Space>
      </Card>
    </div>
  )
}

