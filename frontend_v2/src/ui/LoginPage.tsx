import { FormEvent, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Alert, Button, Card, Form, Input, Segmented, Space, Typography } from 'antd'
import { LockOutlined, UserOutlined } from '@ant-design/icons'
import { useAuth } from './auth'
import { exchangeTelegramOidc, getTelegramOidcConfig } from '../lib/api'

const OIDC_STATE_KEY = 'tg_oidc_state'
const OIDC_VERIFIER_KEY = 'tg_oidc_code_verifier'
const OIDC_NONCE_KEY = 'tg_oidc_nonce'

function randomUrlSafe(size = 48): string {
  const bytes = new Uint8Array(size)
  crypto.getRandomValues(bytes)
  return btoa(String.fromCharCode(...bytes)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '')
}

async function sha256base64url(input: string): Promise<string> {
  const data = new TextEncoder().encode(input)
  const digest = await crypto.subtle.digest('SHA-256', data)
  const bytes = new Uint8Array(digest)
  return btoa(String.fromCharCode(...bytes)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '')
}

export function LoginPage() {
  const navigate = useNavigate()
  const { login } = useAuth()
  const [mode, setMode] = useState<'password' | 'otp' | 'telegram'>('password')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [otpCode, setOtpCode] = useState('')
  const [otpRequested, setOtpRequested] = useState(false)
  const [otpInfo, setOtpInfo] = useState<string | null>(null)
  const [telegramOidcReady, setTelegramOidcReady] = useState<boolean | null>(null)
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
    const params = new URLSearchParams(window.location.search)
    const code = params.get('code')
    const state = params.get('state')
    const errorCode = params.get('error')
    if (!code && !errorCode) return

    const expectedState = sessionStorage.getItem(OIDC_STATE_KEY) || ''
    const codeVerifier = sessionStorage.getItem(OIDC_VERIFIER_KEY) || ''
    const nonce = sessionStorage.getItem(OIDC_NONCE_KEY) || ''

    if (errorCode) {
      setError(`Telegram OIDC error: ${errorCode}`)
      return
    }
    if (!state || state !== expectedState) {
      setError('OIDC state mismatch. Повторите вход.')
      return
    }
    if (!codeVerifier) {
      setError('OIDC code_verifier missing. Повторите вход.')
      return
    }

    setLoading(true)
    void (async () => {
      try {
        const cfg = await getTelegramOidcConfig()
        const auth = await exchangeTelegramOidc({
          code,
          code_verifier: codeVerifier,
          redirect_uri: cfg.redirect_uri,
          nonce,
        })
        login({ tokens: { access: auth.access, refresh: auth.refresh }, username: auth.username })
        sessionStorage.removeItem(OIDC_STATE_KEY)
        sessionStorage.removeItem(OIDC_VERIFIER_KEY)
        sessionStorage.removeItem(OIDC_NONCE_KEY)
        navigate('/requests', { replace: true })
      } catch (err: any) {
        setError(err?.message || 'Не удалось завершить вход через Telegram OIDC')
      } finally {
        setLoading(false)
      }
    })()
  }, [login, navigate])

  async function startTelegramOidc() {
    setError(null)
    setLoading(true)
    try {
      const cfg = await getTelegramOidcConfig()
      const codeVerifier = randomUrlSafe(64)
      const codeChallenge = await sha256base64url(codeVerifier)
      const state = randomUrlSafe(24)
      const nonce = randomUrlSafe(24)
      sessionStorage.setItem(OIDC_VERIFIER_KEY, codeVerifier)
      sessionStorage.setItem(OIDC_STATE_KEY, state)
      sessionStorage.setItem(OIDC_NONCE_KEY, nonce)

      const params = new URLSearchParams({
        client_id: cfg.client_id,
        redirect_uri: cfg.redirect_uri,
        response_type: 'code',
        scope: cfg.scope || 'openid profile telegram:bot_access',
        state,
        code_challenge: codeChallenge,
        code_challenge_method: 'S256',
        nonce,
      })
      window.location.assign(`${cfg.authorization_endpoint}?${params.toString()}`)
    } catch (err: any) {
      setError(err?.message || 'Telegram OIDC не настроен')
      setLoading(false)
      setTelegramOidcReady(false)
    }
  }

  useEffect(() => {
    let disposed = false
    void (async () => {
      try {
        await getTelegramOidcConfig()
        if (!disposed) setTelegramOidcReady(true)
      } catch {
        if (!disposed) setTelegramOidcReady(false)
      }
    })()
    return () => {
      disposed = true
    }
  }, [])

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
              { label: 'Telegram OIDC', value: 'telegram' },
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
              {telegramOidcReady === null ? <Typography.Text type="secondary">Загрузка настроек Telegram...</Typography.Text> : null}
              {telegramOidcReady === false ? (
                <Alert
                  type="warning"
                  showIcon
                  message="Telegram OIDC не настроен"
                  description="Укажите OIDC Client ID / Secret / Redirect URI в настройках тенанта."
                />
              ) : null}
              <Typography.Text type="secondary">
                Вход через Telegram OIDC. После авторизации Telegram вернет вас обратно в это окно.
              </Typography.Text>
              <Button type="primary" onClick={() => void startTelegramOidc()} loading={loading} disabled={telegramOidcReady !== true}>
                Войти через Telegram
              </Button>
              {error ? <Alert type="error" showIcon message="Ошибка Telegram OIDC" description={error} /> : null}
            </Space>
          )}
        </Space>
      </Card>
    </div>
  )
}

