import { renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest'
import { PHONE_MEDIA_QUERY, TOUCH_PHONE_LANDSCAPE_QUERY, useIsPhone, usePortalMobileMode } from './useIsPhone'
import { resetViewport, setViewport } from '../test/viewport'
import { Grid } from 'antd'

const originalMatchMedia = window.matchMedia

/** Replaces matchMedia for this file only; restored after each test. */
function stubMatchMedia(phone: boolean, touchLandscape = false) {
  const stub = vi.fn((query: string) => ({
    matches: query === PHONE_MEDIA_QUERY ? phone : query === TOUCH_PHONE_LANDSCAPE_QUERY ? touchLandscape : false,
    media: query,
    onchange: null,
    addListener: () => undefined,
    removeListener: () => undefined,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    dispatchEvent: () => false,
  }))
  Object.defineProperty(window, 'matchMedia', { configurable: true, writable: true, value: stub })
  return stub
}

describe('useIsPhone', () => {
  let breakpointSpy: MockInstance | null = null

  beforeEach(() => {
    window.history.replaceState(null, '', '/app/requests')
    delete window.Telegram
  })

  afterEach(() => {
    breakpointSpy?.mockRestore()
    breakpointSpy = null
    resetViewport()
    Object.defineProperty(window, 'matchMedia', { configurable: true, writable: true, value: originalMatchMedia })
    window.history.replaceState(null, '', '/')
    delete window.Telegram
  })

  it('reads the width synchronously while antd has no breakpoints yet: phone', () => {
    breakpointSpy = vi.spyOn(Grid, 'useBreakpoint').mockReturnValue({})
    const stub = stubMatchMedia(true)
    const { result } = renderHook(() => useIsPhone())
    expect(result.current).toBe(true)
    expect(stub).toHaveBeenCalledWith(PHONE_MEDIA_QUERY)
  })

  it('reads the width synchronously while antd has no breakpoints yet: desktop', () => {
    breakpointSpy = vi.spyOn(Grid, 'useBreakpoint').mockReturnValue({})
    stubMatchMedia(false)
    const { result } = renderHook(() => useIsPhone())
    expect(result.current).toBe(false)
  })

  it('follows antd once the breakpoints are known', () => {
    breakpointSpy = vi.spyOn(Grid, 'useBreakpoint').mockReturnValue({ md: true })
    // A stale media answer must not win over antd.
    stubMatchMedia(true)
    expect(renderHook(() => useIsPhone()).result.current).toBe(false)
    breakpointSpy.mockReturnValue({ xs: true, md: false })
    expect(renderHook(() => useIsPhone()).result.current).toBe(true)
  })

  it('stays on for a phone turned to landscape wider than 768 px, so rotation does not remount the page', () => {
    breakpointSpy = vi.spyOn(Grid, 'useBreakpoint').mockReturnValue({ xs: true, md: false })
    stubMatchMedia(true, false)
    const { result, rerender } = renderHook(() => useIsPhone())
    expect(result.current).toBe(true)
    // Rotated: 844 x 390 on a touch-only screen.
    breakpointSpy.mockReturnValue({ xs: false, sm: true, md: true, lg: true })
    stubMatchMedia(false, true)
    rerender()
    expect(result.current).toBe(true)
  })

  it('keeps the desktop layout on a wide screen with a mouse (touch laptops included)', () => {
    breakpointSpy = vi.spyOn(Grid, 'useBreakpoint').mockReturnValue({ sm: true, md: true, lg: true })
    const stub = stubMatchMedia(false, false)
    expect(renderHook(() => useIsPhone()).result.current).toBe(false)
    expect(stub).toHaveBeenCalledWith(TOUCH_PHONE_LANDSCAPE_QUERY)
  })
})

describe('usePortalMobileMode', () => {
  beforeEach(() => {
    window.history.replaceState(null, '', '/app/requests')
    delete window.Telegram
  })

  afterEach(() => {
    resetViewport()
    window.history.replaceState(null, '', '/')
    delete window.Telegram
  })

  it('is on for the portal on a phone and off on a desktop', () => {
    setViewport('phone')
    expect(renderHook(() => usePortalMobileMode()).result.current).toBe(true)
    expect(renderHook(() => usePortalMobileMode('portal')).result.current).toBe(true)
    setViewport('desktop')
    expect(renderHook(() => usePortalMobileMode()).result.current).toBe(false)
  })

  it('never turns on for variant="telegram", even at 360 px', () => {
    setViewport('phone')
    expect(renderHook(() => usePortalMobileMode('telegram')).result.current).toBe(false)
  })

  it('never turns on under /tg/ (the Mini App routes)', () => {
    setViewport('phone')
    window.history.replaceState(null, '', '/app/tg/requests/new')
    expect(renderHook(() => usePortalMobileMode()).result.current).toBe(false)
  })

  it('never turns on when Telegram passes initData', () => {
    setViewport('phone')
    window.Telegram = { WebApp: { initData: 'query_id=1', initDataUnsafe: {}, ready: () => undefined } }
    expect(renderHook(() => usePortalMobileMode()).result.current).toBe(false)
  })
})
