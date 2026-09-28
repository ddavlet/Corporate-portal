import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

// Each request stays pending until a test settles it by id.
const pending = new Map<number, { resolve: (value: unknown) => void; reject: (error: unknown) => void }>()
vi.mock('../../../../lib/reportsApi', () => ({
  getReportRequestDetail: (id: number) =>
    new Promise((resolve, reject) => {
      pending.set(id, { resolve, reject })
    }),
}))

import { ApiError } from '../../../../lib/api'
import { useRequestPreview } from './RequestPreview'

function Host() {
  const preview = useRequestPreview()
  return (
    <>
      <button type="button" onClick={() => preview.open(7)}>
        open request
      </button>
      <button type="button" onClick={() => preview.open(8)}>
        open other
      </button>
      {preview.modal}
    </>
  )
}

describe('useRequestPreview', () => {
  it('stacks the request card above the drill-down panel', async () => {
    render(<Host />)
    fireEvent.click(screen.getByText('open request'))
    const wrap = await waitFor(() => {
      const element = document.querySelector<HTMLElement>('.ant-modal-wrap')
      expect(element).not.toBeNull()
      return element as HTMLElement
    })
    // Drawers sit at z-index 1000 and keep their container once opened; the card must be above them.
    expect(Number(wrap.style.zIndex)).toBeGreaterThan(1000)
  })

  it('shows the request opened last even when an earlier one answers later', async () => {
    render(<Host />)
    fireEvent.click(screen.getByText('open request'))
    fireEvent.click(screen.getByText('open other'))
    await act(async () => pending.get(8)?.reject(new ApiError(404, 'Заявка 8 недоступна')))
    await act(async () => pending.get(7)?.reject(new ApiError(404, 'Заявка 7 недоступна')))
    expect(await screen.findByText('Заявка 8 недоступна')).toBeInTheDocument()
    expect(screen.queryByText('Заявка 7 недоступна')).toBeNull()
  })
})
