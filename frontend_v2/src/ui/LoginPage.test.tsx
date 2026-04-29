import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { LoginPage } from './LoginPage'

const loginMock = vi.fn()
const getTelegramOidcConfigMock = vi.fn()

vi.mock('./auth', () => ({
  useAuth: () => ({ login: loginMock }),
}))

vi.mock('../lib/api', () => ({
  getTelegramOidcConfig: (...args: unknown[]) => getTelegramOidcConfigMock(...args),
  exchangeTelegramOidc: vi.fn(),
}))

describe('LoginPage OIDC', () => {
  beforeEach(() => {
    loginMock.mockReset()
    getTelegramOidcConfigMock.mockReset()
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
