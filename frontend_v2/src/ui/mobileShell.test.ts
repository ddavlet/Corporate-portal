import { describe, expect, it, vi } from 'vitest'
import { createMobileHeaderStore } from './mobileShell'

describe('createMobileHeaderStore', () => {
  it('starts empty and returns what was set', () => {
    const store = createMobileHeaderStore()
    expect(store.get()).toBeNull()
    store.set({ title: 'Заявка №1', back: '/requests' })
    expect(store.get()).toEqual({ title: 'Заявка №1', back: '/requests' })
    store.set(null)
    expect(store.get()).toBeNull()
  })

  it('notifies every subscriber on each change', () => {
    const store = createMobileHeaderStore()
    const first = vi.fn()
    const second = vi.fn()
    store.subscribe(first)
    store.subscribe(second)
    store.set({ title: 'A' })
    store.set(null)
    expect(first).toHaveBeenCalledTimes(2)
    expect(second).toHaveBeenCalledTimes(2)
  })

  it('stops notifying after unsubscribe', () => {
    const store = createMobileHeaderStore()
    const listener = vi.fn()
    const unsubscribe = store.subscribe(listener)
    store.set({ title: 'A' })
    unsubscribe()
    store.set({ title: 'B' })
    expect(listener).toHaveBeenCalledTimes(1)
  })

  it('keeps separate stores independent', () => {
    const a = createMobileHeaderStore()
    const b = createMobileHeaderStore()
    a.set({ title: 'A' })
    expect(b.get()).toBeNull()
  })
})
