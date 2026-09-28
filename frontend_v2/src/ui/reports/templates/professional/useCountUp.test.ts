import { act, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { prefersReducedMotion, useCountUp } from './useCountUp'

function motion(reduce: boolean) {
  vi.spyOn(window, 'matchMedia').mockImplementation(
    (query: string) =>
      ({
        matches: reduce && query.includes('reduce'),
        media: query,
        onchange: null,
        addListener: () => undefined,
        removeListener: () => undefined,
        addEventListener: () => undefined,
        removeEventListener: () => undefined,
        dispatchEvent: () => false,
      }) as MediaQueryList,
  )
}

describe('useCountUp', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('shows the final number at once when the viewer asked for less motion', () => {
    motion(true)
    expect(prefersReducedMotion()).toBe(true)
    const { result } = renderHook(() => useCountUp(1500))
    expect(result.current).toBe(1500)
  })

  it('counts up to the number and stops there', () => {
    motion(false)
    vi.useFakeTimers({ toFake: ['requestAnimationFrame', 'cancelAnimationFrame', 'performance'] })
    const { result } = renderHook(() => useCountUp(1000, 900))
    expect(result.current).toBe(0)
    act(() => {
      vi.advanceTimersByTime(450)
    })
    expect(result.current).toBeGreaterThan(0)
    expect(result.current).toBeLessThan(1000)
    act(() => {
      vi.advanceTimersByTime(600)
    })
    expect(result.current).toBe(1000)
  })
})
