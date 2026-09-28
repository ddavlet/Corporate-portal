import { afterEach, describe, expect, it, vi } from 'vitest'
import { saveFile } from './saveFile'

describe('saveFile', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('downloads through a link named after the file and frees the memory later', () => {
    vi.useFakeTimers()
    const createObjectURL = vi.fn(() => 'blob:report')
    const revokeObjectURL = vi.fn()
    Object.defineProperty(URL, 'createObjectURL', { value: createObjectURL, configurable: true })
    Object.defineProperty(URL, 'revokeObjectURL', { value: revokeObjectURL, configurable: true })
    const clicked: string[] = []
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      clicked.push(`${this.download}|${this.getAttribute('href')}`)
    })

    saveFile({ blob: new Blob(['x']), filename: 'PnL_2026-08_demo_2026-09-23.xlsx' })

    expect(clicked).toEqual(['PnL_2026-08_demo_2026-09-23.xlsx|blob:report'])
    expect(document.querySelector('a[download]')).toBeNull()
    expect(revokeObjectURL).not.toHaveBeenCalled()
    vi.advanceTimersByTime(60_000)
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:report')
  })
})
