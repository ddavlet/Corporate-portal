import { afterEach, describe, expect, it, vi } from 'vitest'
import { waitForQuietDocument } from './helpers'

describe('waitForQuietDocument', () => {
  afterEach(() => {
    vi.useRealTimers()
    document.body.innerHTML = ''
  })

  it('waits until the page has not changed for the quiet period', async () => {
    vi.useFakeTimers()
    const box = document.body.appendChild(document.createElement('div'))
    const settled = vi.fn()
    void waitForQuietDocument(50, 1000).then(settled)

    await vi.advanceTimersByTimeAsync(40)
    box.textContent = 'still rendering'
    await vi.advanceTimersByTimeAsync(40)
    // 80 ms since the start, but only 40 ms since the last change.
    expect(settled).not.toHaveBeenCalled()

    await vi.advanceTimersByTimeAsync(20)
    expect(settled).toHaveBeenCalledTimes(1)
  })

  it('stops waiting at the limit when the page keeps changing', async () => {
    vi.useFakeTimers()
    const box = document.body.appendChild(document.createElement('div'))
    let frame = 0
    const ticker = setInterval(() => {
      frame += 1
      box.textContent = String(frame)
    }, 10)
    const settled = vi.fn()
    void waitForQuietDocument(50, 200).then(settled)

    await vi.advanceTimersByTimeAsync(190)
    expect(settled).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(20)
    expect(settled).toHaveBeenCalledTimes(1)
    clearInterval(ticker)
  })
})
