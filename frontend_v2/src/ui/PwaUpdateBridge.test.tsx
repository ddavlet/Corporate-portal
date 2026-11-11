import { act, render } from '@testing-library/react'
import { MemoryRouter, useNavigate } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { PwaUpdateBridge } from './PwaUpdateBridge'

let updateReady = false
vi.mock('../lib/pwa', () => ({ isPwaUpdateReady: () => updateReady }))

let navigateTo: (to: string) => void = () => undefined

function NavigateHandle() {
  const navigate = useNavigate()
  navigateTo = (to) => navigate(to)
  return null
}

function renderBridge(reload: () => void) {
  return render(
    <MemoryRouter initialEntries={['/requests']}>
      <NavigateHandle />
      <PwaUpdateBridge reload={reload} />
    </MemoryRouter>,
  )
}

describe('PwaUpdateBridge', () => {
  beforeEach(() => {
    updateReady = false
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' })
  })

  it('never reloads on mount, even with an update waiting', () => {
    updateReady = true
    const reload = vi.fn()
    renderBridge(reload)
    expect(reload).not.toHaveBeenCalled()
  })

  it('does not reload on navigation without a new version', () => {
    const reload = vi.fn()
    renderBridge(reload)
    act(() => navigateTo('/cash'))
    expect(reload).not.toHaveBeenCalled()
  })

  it('reloads on the first route change after the update flag is set', () => {
    const reload = vi.fn()
    renderBridge(reload)
    updateReady = true
    expect(reload).not.toHaveBeenCalled()
    act(() => navigateTo('/cash'))
    expect(reload).toHaveBeenCalledTimes(1)
  })

  it('does not reload a hidden tab', () => {
    const reload = vi.fn()
    renderBridge(reload)
    updateReady = true
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' })
    act(() => navigateTo('/cash'))
    expect(reload).not.toHaveBeenCalled()
  })
})
