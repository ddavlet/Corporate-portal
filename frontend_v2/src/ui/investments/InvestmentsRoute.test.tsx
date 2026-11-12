import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { resetViewport, setViewport, type ViewportKind } from '../../test/viewport'
import { InvestmentCollectRoute, InvestmentCreateRoute, InvestmentsRoute, InvestReturnCreateRoute } from './InvestmentsRoute'

vi.mock('../InvestmentsPage', () => ({ InvestmentsPage: () => <div>InvestmentsPage</div> }))
vi.mock('./InvestmentsMobilePage', () => ({ InvestmentsMobilePage: () => <div>InvestmentsMobilePage</div> }))
vi.mock('./InvestReturnCreateMobilePage', () => ({
  InvestReturnCreateMobilePage: () => <div>InvestReturnCreateMobilePage</div>,
}))
vi.mock('./InvestmentCollectMobilePage', () => ({
  InvestmentCollectMobilePage: () => <div>InvestmentCollectMobilePage</div>,
}))
vi.mock('./InvestmentCreateMobilePage', () => ({
  InvestmentCreateMobilePage: () => <div>InvestmentCreateMobilePage</div>,
}))

function LocationProbe() {
  const location = useLocation()
  return <div data-testid="location">{location.pathname}</div>
}

function renderAt(url: string, viewport: ViewportKind) {
  setViewport(viewport)
  return render(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route path="/investments" element={<InvestmentsRoute />} />
        <Route path="/investments/returns/new" element={<InvestReturnCreateRoute />} />
        <Route path="/investments/collect" element={<InvestmentCollectRoute />} />
        <Route path="/investments/new" element={<InvestmentCreateRoute />} />
      </Routes>
      <LocationProbe />
    </MemoryRouter>,
  )
}

const currentPath = () => screen.getByTestId('location').textContent

afterEach(() => {
  resetViewport()
  delete window.Telegram
})

describe('InvestmentsRoute', () => {
  it('opens the two actions on a phone and the desktop tabs on a desktop', () => {
    const phone = renderAt('/investments', 'phone')
    expect(screen.getByText('InvestmentsMobilePage')).toBeInTheDocument()
    expect(screen.queryByText('InvestmentsPage')).toBeNull()
    phone.unmount()

    renderAt('/investments', 'desktop')
    expect(screen.getByText('InvestmentsPage')).toBeInTheDocument()
    expect(screen.queryByText('InvestmentsMobilePage')).toBeNull()
  })

  it('opens the phone forms on a phone', () => {
    const first = renderAt('/investments/returns/new', 'phone')
    expect(screen.getByText('InvestReturnCreateMobilePage')).toBeInTheDocument()
    first.unmount()

    const second = renderAt('/investments/collect', 'phone')
    expect(screen.getByText('InvestmentCollectMobilePage')).toBeInTheDocument()
    second.unmount()

    renderAt('/investments/new', 'phone')
    expect(screen.getByText('InvestmentCreateMobilePage')).toBeInTheDocument()
    expect(screen.queryByText('InvestmentsMobilePage')).toBeNull()
  })

  it('sends the phone form addresses to /investments on a desktop', () => {
    for (const url of ['/investments/returns/new', '/investments/collect', '/investments/new']) {
      const { unmount } = renderAt(url, 'desktop')
      expect(currentPath()).toBe('/investments')
      expect(screen.getByText('InvestmentsPage')).toBeInTheDocument()
      expect(screen.queryByText('InvestReturnCreateMobilePage')).toBeNull()
      expect(screen.queryByText('InvestmentCollectMobilePage')).toBeNull()
      expect(screen.queryByText('InvestmentCreateMobilePage')).toBeNull()
      unmount()
    }
  })

  it('keeps the desktop branch in Telegram WebApp at phone width', () => {
    window.Telegram = { WebApp: { initData: 'query_id=1', initDataUnsafe: {}, ready: () => undefined } }

    const first = renderAt('/investments', 'phone')
    expect(screen.getByText('InvestmentsPage')).toBeInTheDocument()
    expect(screen.queryByText('InvestmentsMobilePage')).toBeNull()
    first.unmount()

    const second = renderAt('/investments/collect', 'phone')
    expect(currentPath()).toBe('/investments')
    expect(screen.queryByText('InvestmentCollectMobilePage')).toBeNull()
    second.unmount()

    renderAt('/investments/new', 'phone')
    expect(currentPath()).toBe('/investments')
    expect(screen.queryByText('InvestmentCreateMobilePage')).toBeNull()
  })
})
