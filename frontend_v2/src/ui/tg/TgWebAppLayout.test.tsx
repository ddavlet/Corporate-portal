import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { TgWebAppLayout } from './TgWebAppLayout'
import { exchangeTelegramWebApp } from '../../lib/api'
import { resetViewport, setViewport } from '../../test/viewport'

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

describe('TgWebAppLayout at phone width (the portal mobile layout never applies)', () => {
  beforeEach(() => {
    document.documentElement.className = ''
    vi.mocked(exchangeTelegramWebApp).mockResolvedValue({ access: 'a', refresh: 'r', username: 'ivan' } as never)
  })

  afterEach(() => {
    resetViewport()
    vi.mocked(exchangeTelegramWebApp).mockReset()
    delete (window as Window).Telegram
  })

  it.each(['/tg/requests/new', '/tg/requests/12'])('keeps the tg-* markup at 360 px on %s', async (path) => {
    setViewport('phone')
    ;(window as Window).Telegram = {
      WebApp: {
        initData: 'query_id=1',
        initDataUnsafe: {},
        ready: vi.fn(),
        expand: vi.fn(),
        platform: 'android',
        isVersionAtLeast: () => false,
      },
    }
    const { container } = render(
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/tg" element={<TgWebAppLayout />}>
            <Route path="requests/new" element={<div>Создание заявки</div>} />
            <Route path="requests/:id" element={<div>Карточка заявки</div>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    )
    expect(await screen.findByText(/Создание заявки|Карточка заявки/)).toBeInTheDocument()
    expect(container.querySelector('.tg-webapp-root > .tg-webapp-inner')).not.toBeNull()
    expect(container.querySelector('.m-root, .m-header, .m-content, .m-bottom-bar')).toBeNull()
    expect(screen.queryByTestId('mobile-shell')).toBeNull()
    expect(screen.queryByTestId('install-app-prompt')).toBeNull()
  })
})
