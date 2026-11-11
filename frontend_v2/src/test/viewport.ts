import { Grid } from 'antd'
import { afterEach, beforeEach, vi, type MockInstance } from 'vitest'

export type ViewportKind = 'phone' | 'desktop'

const SCREENS: Record<ViewportKind, Record<string, boolean>> = {
  phone: { xs: true, sm: true, md: false, lg: false, xl: false, xxl: false },
  desktop: { xs: false, sm: true, md: true, lg: true, xl: true, xxl: false },
}

let spy: MockInstance | null = null

/**
 * Pins `Grid.useBreakpoint()` for the current test. Call it before rendering: a component must not see the hook
 * change under it. matchMedia is not touched, so the other media queries of the page behave as in jsdom.
 */
export function setViewport(kind: ViewportKind): void {
  spy?.mockRestore()
  spy = vi.spyOn(Grid, 'useBreakpoint').mockReturnValue(SCREENS[kind])
}

/** Puts the real `Grid.useBreakpoint` back. */
export function resetViewport(): void {
  spy?.mockRestore()
  spy = null
}

/**
 * Pins the viewport for every test of the surrounding `describe` (or file) and restores it after each test, so the
 * pin never leaks into other tests. A test may still switch it with `setViewport` before it renders.
 */
export function installViewport(kind: ViewportKind): void {
  beforeEach(() => setViewport(kind))
  afterEach(() => resetViewport())
}
