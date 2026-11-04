import { render } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { TgWebAppLayout } from './TgWebAppLayout'

vi.mock('../../lib/api', () => ({
  exchangeTelegramWebApp: vi.fn(),
  setTgTokens: vi.fn(),
}))
vi.mock('../auth', () => ({ useAuth: () => ({ login: vi.fn() }) }))
vi.mock('../moduleAccess', () => ({ ModuleAccessProvider: ({ children }: { children: unknown }) => children }))

function mountWith(overrides: Partial<TelegramWebApp>) {
  const requestFullscreen = vi.fn()
  ;(window as Window).Telegram = {
    WebApp: {
      initData: '',
      initDataUnsafe: {},
      ready: vi.fn(),
      expand: vi.fn(),
      isFullscreen: false,
      isVersionAtLeast: () => true,
      requestFullscreen,
      ...overrides,
    },
  }
  render(
    <MemoryRouter initialEntries={['/tg']}>
      <TgWebAppLayout />
    </MemoryRouter>,
  )
  return requestFullscreen
}

describe('TgWebAppLayout fullscreen', () => {
  beforeEach(() => {
    document.documentElement.className = ''
  })

  it('requests fullscreen on mobile Telegram 8.0+', () => {
    expect(mountWith({ platform: 'ios' })).toHaveBeenCalledTimes(1)
  })

  it('does not request fullscreen on desktop', () => {
    expect(mountWith({ platform: 'tdesktop' })).not.toHaveBeenCalled()
    expect(mountWith({ platform: 'weba' })).not.toHaveBeenCalled()
  })
})
