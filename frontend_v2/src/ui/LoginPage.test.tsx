import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { LoginPage } from './LoginPage'
import { installViewport, setViewport } from '../test/viewport'
import { createJsonResponse } from '../test/helpers'

// The page reads the breakpoint (phone layout): desktop unless a test switches to the phone.
installViewport('desktop')

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

describe('LoginPage on a phone', () => {
  const fetchMock = vi.fn()

  beforeEach(() => {
    setViewport('phone')
    loginMock.mockReset()
    getTelegramOidcConfigMock.mockReset()
    getTelegramOidcConfigMock.mockResolvedValue({})
    portalState.shared = false
    fetchMock.mockReset()
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  function renderLogin() {
    return render(
      <MemoryRouter initialEntries={['/login']}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/requests" element={<div>Лента заявок</div>} />
        </Routes>
      </MemoryRouter>,
    )
  }

  function field(autocomplete: string): HTMLInputElement {
    const input = document.querySelector<HTMLInputElement>(`input[autocomplete="${autocomplete}"]`)
    if (!input) throw new Error(`no field ${autocomplete}`)
    return input
  }

  it('fits the screen: the card is at most 420 px wide', () => {
    renderLogin()
    const card = screen.getByText('Вход в систему').closest('.ant-card')
    expect(card).toHaveStyle({ width: '100%', maxWidth: '420px' })
  })

  it('signs in with a password', async () => {
    fetchMock.mockResolvedValue(createJsonResponse(200, { access: 'a1', refresh: 'r1' }))
    renderLogin()
    fireEvent.change(field('username'), { target: { value: 'ivan' } })
    fireEvent.change(field('current-password'), { target: { value: 'secret' } })
    fireEvent.click(screen.getByRole('button', { name: 'Войти' }))
    await waitFor(() =>
      expect(loginMock).toHaveBeenCalledWith({ tokens: { access: 'a1', refresh: 'r1' }, username: 'ivan' }),
    )
    expect(fetchMock).toHaveBeenCalledWith('/api/auth/token/', expect.objectContaining({ method: 'POST' }))
    expect(await screen.findByText('Лента заявок')).toBeInTheDocument()
  })

  it('signs in with a Telegram code', async () => {
    fetchMock
      .mockResolvedValueOnce(createJsonResponse(200, { detail: 'Код отправлен.' }))
      .mockResolvedValueOnce(createJsonResponse(200, { access: 'a2', refresh: 'r2' }))
    renderLogin()
    fireEvent.click(screen.getByText('OTP в Telegram'))
    fireEvent.change(field('username'), { target: { value: 'ivan' } })
    fireEvent.click(screen.getByRole('button', { name: 'Получить OTP' }))
    expect(await screen.findByText('Код отправлен.')).toBeInTheDocument()
    fireEvent.change(field('one-time-code'), { target: { value: '123456' } })
    fireEvent.click(screen.getByRole('button', { name: 'Подтвердить и войти' }))
    await waitFor(() =>
      expect(loginMock).toHaveBeenCalledWith({ tokens: { access: 'a2', refresh: 'r2' }, username: 'ivan' }),
    )
    expect(fetchMock).toHaveBeenNthCalledWith(1, '/api/auth/otp/request/', expect.objectContaining({ method: 'POST' }))
    expect(fetchMock).toHaveBeenNthCalledWith(2, '/api/auth/otp/verify/', expect.objectContaining({ method: 'POST' }))
  })
})
