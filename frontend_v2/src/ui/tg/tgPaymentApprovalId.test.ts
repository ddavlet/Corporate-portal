import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { getTelegramWebAppStartParam, resolvePaymentApprovalId } from './tgPaymentApprovalId'

type MutableWindow = Window &
  typeof globalThis & {
    Telegram?: {
      WebApp?: TelegramWebApp
    }
  }

function setWindowLocationSearch(search: string) {
  const win = (globalThis as { window: MutableWindow }).window
  Object.defineProperty(win, 'location', {
    value: new URL(`https://example.com/${search}`),
    configurable: true,
  })
}

function getWindow(): MutableWindow {
  return (globalThis as { window: MutableWindow }).window
}

function createTelegramWebApp(startParam?: string): TelegramWebApp {
  return {
    initData: '',
    initDataUnsafe: startParam ? { start_param: startParam } : {},
    ready: () => {},
  }
}

describe('getTelegramWebAppStartParam', () => {
  beforeEach(() => {
    Object.defineProperty(globalThis, 'window', {
      value: { location: new URL('https://example.com/') },
      configurable: true,
    })
  })

  afterEach(() => {
    const win = getWindow()
    delete win.Telegram
    setWindowLocationSearch('')
  })

  it('returns Telegram start_param with trimming', () => {
    const win = getWindow()
    win.Telegram = { WebApp: createTelegramWebApp('  approval_42  ') }
    setWindowLocationSearch('?tgWebAppStartParam=123')

    expect(getTelegramWebAppStartParam()).toBe('approval_42')
  })

  it('falls back to tgWebAppStartParam query param', () => {
    setWindowLocationSearch('?tgWebAppStartParam=approval-77')

    expect(getTelegramWebAppStartParam()).toBe('approval-77')
  })
})

describe('resolvePaymentApprovalId', () => {
  beforeEach(() => {
    Object.defineProperty(globalThis, 'window', {
      value: { location: new URL('https://example.com/') },
      configurable: true,
    })
  })

  afterEach(() => {
    const win = getWindow()
    delete win.Telegram
    setWindowLocationSearch('')
  })

  it('prefers approval_id from query string', () => {
    const params = new URLSearchParams('approval_id=15')
    const win = getWindow()
    win.Telegram = { WebApp: createTelegramWebApp('approval_999') }

    expect(resolvePaymentApprovalId(params)).toBe(15)
  })

  it('parses numeric start_param when approval_id is missing', () => {
    const params = new URLSearchParams('')
    const win = getWindow()
    win.Telegram = { WebApp: createTelegramWebApp('321') }

    expect(resolvePaymentApprovalId(params)).toBe(321)
  })

  it('parses prefixed start_param in approval_<id> format', () => {
    const params = new URLSearchParams('')
    const win = getWindow()
    win.Telegram = { WebApp: createTelegramWebApp('approval-88') }

    expect(resolvePaymentApprovalId(params)).toBe(88)
  })

  it('returns 0 for invalid values', () => {
    const params = new URLSearchParams('approval_id=0')
    const win = getWindow()
    win.Telegram = { WebApp: createTelegramWebApp('not-an-id') }

    expect(resolvePaymentApprovalId(params)).toBe(0)
  })
})
