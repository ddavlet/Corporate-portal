import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

vi.mock('../../../../lib/reportsApi', () => ({ getReportRequestDetail: () => new Promise(() => undefined) }))

// A stub card that shows which instalment it was asked to highlight.
vi.mock('../../../requests/RequestDetailModal', () => ({
  RequestDetailModal: ({ open, highlightPeriodIndex }: { open: boolean; highlightPeriodIndex?: number | null }) =>
    open ? <div data-testid="request-card">{`highlight:${highlightPeriodIndex ?? 'none'}`}</div> : null,
}))

import { useRequestPreview } from './RequestPreview'

function Host() {
  const preview = useRequestPreview()
  return (
    <>
      <button type="button" onClick={() => preview.open(7, 2)}>
        amortized
      </button>
      <button type="button" onClick={() => preview.open(8, null)}>
        one-off
      </button>
      {preview.modal}
    </>
  )
}

describe('useRequestPreview highlight', () => {
  it('passes the instalment of the clicked cell to the request card', () => {
    render(<Host />)
    fireEvent.click(screen.getByText('amortized'))
    expect(screen.getByTestId('request-card')).toHaveTextContent('highlight:2')
    fireEvent.click(screen.getByText('one-off'))
    expect(screen.getByTestId('request-card')).toHaveTextContent('highlight:none')
  })
})
