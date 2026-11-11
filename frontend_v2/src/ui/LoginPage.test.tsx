import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { LoginPage } from './LoginPage'

const loginMock = vi.fn()
const getTelegramOidcConfigMock = vi.fn()

vi.mock('./auth', () => ({
  useAuth: () => ({ login: loginMock }),
}))

const portalState = vi.hoisted(() => ({ shared: false }))

vi.mock('../lib/portalMode', () => ({ isSharedAppMode: () => portalState.shared }))

vi.mock('../lib/api', () => ({
  getTelegramOidcConfig: (...args: unknown[]) => getTelegramOidcConfigMock(...args),
  exchangeTelegramOidc: vi.fn(),
}))

describe('LoginPage OIDC', () => {
  beforeEach(() => {
    loginMock.mockReset()
    getTelegramOidcConfigMock.mockReset()
    portalState.shared = false
  })

  it('shows oidc warning when tenant config missing', async () => {
    getTelegramOidcConfigMock.mockRejectedValue(new Error('not configured'))
    render(
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>,
    )
    const telegramTab = await screen.findByText('Telegram OIDC')
    telegramTab.click()
    await waitFor(() => {
      expect(screen.getByText('Telegram OIDC не настроен')).toBeInTheDocument()
    })
  })
})

describe('LoginPage on the shared app host (crit. 13)', () => {
  beforeEach(() => {
    getTelegramOidcConfigMock.mockReset()
    getTelegramOidcConfigMock.mockResolvedValue({})
    portalState.shared = false
  })

  function renderLogin() {
    return render(
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>,
    )
  }

  it('offers only password and OTP and does not touch Telegram OIDC', async () => {
    portalState.shared = true
    renderLogin()
    expect(screen.getAllByText('Пароль').length).toBeGreaterThan(0)
    expect(screen.getByText('OTP в Telegram')).toBeInTheDocument()
    expect(screen.queryByText('Telegram OIDC')).toBeNull()
    expect(screen.getByText('Один вход для всех ваших компаний. Компанию можно выбрать после входа.')).toBeInTheDocument()
    expect(getTelegramOidcConfigMock).not.toHaveBeenCalled()
  })

  it('keeps all three ways in on a tenant subdomain', async () => {
    renderLogin()
    expect(screen.getAllByText('Пароль').length).toBeGreaterThan(0)
    expect(screen.getByText('OTP в Telegram')).toBeInTheDocument()
    expect(screen.getByText('Telegram OIDC')).toBeInTheDocument()
    expect(screen.getByText(/Тенант определяется автоматически/)).toBeInTheDocument()
    await waitFor(() => expect(getTelegramOidcConfigMock).toHaveBeenCalled())
  })
})
