import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { clearAppBadgeSafe, syncAppBadge } from './appBadge'

const nav = navigator as unknown as Record<string, unknown>

function installBadging(setAppBadge: unknown, clearAppBadge: unknown) {
  Object.defineProperty(navigator, 'setAppBadge', { configurable: true, value: setAppBadge })
  Object.defineProperty(navigator, 'clearAppBadge', { configurable: true, value: clearAppBadge })
}

describe('appBadge', () => {
  beforeEach(() => {
    window.history.replaceState(null, '', '/app/')
    delete window.Telegram
  })

  afterEach(() => {
    delete nav.setAppBadge
    delete nav.clearAppBadge
  })

  it('puts the count on the icon', () => {
    const set = vi.fn().mockResolvedValue(undefined)
    const clear = vi.fn().mockResolvedValue(undefined)
    installBadging(set, clear)
    syncAppBadge(3)
    expect(set).toHaveBeenCalledWith(3)
    expect(clear).not.toHaveBeenCalled()
  })

  it('clears the icon at zero', () => {
    const set = vi.fn().mockResolvedValue(undefined)
    const clear = vi.fn().mockResolvedValue(undefined)
    installBadging(set, clear)
    syncAppBadge(0)
    expect(clear).toHaveBeenCalledTimes(1)
    expect(set).not.toHaveBeenCalled()
  })

  it('does nothing and throws nothing without the Badging API', () => {
    expect(() => syncAppBadge(2)).not.toThrow()
    expect(() => syncAppBadge(0)).not.toThrow()
    expect(() => clearAppBadgeSafe()).not.toThrow()
  })

  it('swallows a rejected or throwing call', async () => {
    const set = vi.fn().mockRejectedValue(new DOMException('denied', 'NotAllowedError'))
    const clear = vi.fn(() => {
      throw new Error('not installed')
    })
    installBadging(set, clear)
    expect(() => syncAppBadge(5)).not.toThrow()
    expect(() => clearAppBadgeSafe()).not.toThrow()
    // Let the rejected promise settle: an unhandled rejection would fail the run.
    await Promise.resolve()
    expect(set).toHaveBeenCalledWith(5)
  })

  it('is a no-op inside the Telegram Mini App', () => {
    const set = vi.fn().mockResolvedValue(undefined)
    const clear = vi.fn().mockResolvedValue(undefined)
    installBadging(set, clear)
    window.history.replaceState(null, '', '/app/tg/')
    syncAppBadge(4)
    clearAppBadgeSafe()
    expect(set).not.toHaveBeenCalled()
    expect(clear).not.toHaveBeenCalled()
  })
})
