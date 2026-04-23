import { render } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { useTgWebAppShell } from './useTgWebAppShell'

type TgMock = {
  themeParams?: Record<string, string>
  colorScheme?: 'light' | 'dark'
  onEvent?: (event: string, handler: () => void) => void
  offEvent?: (event: string, handler: () => void) => void
  setBackgroundColor?: (color: string) => void
  setHeaderColor?: (color: string) => void
}

function HookHost() {
  useTgWebAppShell()
  return null
}

describe('useTgWebAppShell', () => {
  beforeEach(() => {
    document.documentElement.className = ''
    document.documentElement.removeAttribute('style')
  })

  it('applies dark theme vars and class', () => {
    const onEvent = vi.fn()
    const offEvent = vi.fn()
    const setBackgroundColor = vi.fn()
    const setHeaderColor = vi.fn()
    ;(window as Window & { Telegram?: { WebApp: TgMock } }).Telegram = {
      WebApp: {
        themeParams: {
          bg_color: '#111',
          secondary_bg_color: '#222',
          text_color: '#fff',
          button_color: '#0f0',
          button_text_color: '#000',
        },
        colorScheme: 'dark',
        onEvent,
        offEvent,
        setBackgroundColor,
        setHeaderColor,
      },
    }

    const { unmount } = render(<HookHost />)
    expect(document.documentElement.classList.contains('tg-twa-dark')).toBe(true)
    expect(document.documentElement.style.getPropertyValue('--tg-bg')).toBe('#111')
    expect(setBackgroundColor).toHaveBeenCalledWith('#111')
    expect(onEvent).toHaveBeenCalledWith('themeChanged', expect.any(Function))

    unmount()
    expect(offEvent).toHaveBeenCalledWith('themeChanged', expect.any(Function))
  })
})
