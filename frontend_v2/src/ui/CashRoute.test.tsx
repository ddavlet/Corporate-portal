import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { resetViewport, setViewport, type ViewportKind } from '../test/viewport'
import { CashRegisterTransferRoute, CashRoute } from './CashRoute'

vi.mock('./CashPage', () => ({ CashPage: () => <div>CashPage</div> }))
vi.mock('./CashMobilePage', () => ({ CashMobilePage: () => <div>CashMobilePage</div> }))
vi.mock('./CashRegisterTransferMobilePage', () => ({
  CashRegisterTransferMobilePage: () => <div>CashRegisterTransferMobilePage</div>,
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
        <Route path="/cash" element={<CashRoute />} />
        <Route path="/cash/transfer" element={<CashRegisterTransferRoute />} />
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

describe('CashRoute', () => {
  it('opens the one action on a phone and the desktop page on a desktop', () => {
    const phone = renderAt('/cash', 'phone')
    expect(screen.getByText('CashMobilePage')).toBeInTheDocument()
    expect(screen.queryByText('CashPage')).toBeNull()
    phone.unmount()

    renderAt('/cash', 'desktop')
    expect(screen.getByText('CashPage')).toBeInTheDocument()
    expect(screen.queryByText('CashMobilePage')).toBeNull()
  })

  it('opens the transfer form on a phone', () => {
    renderAt('/cash/transfer', 'phone')
    expect(screen.getByText('CashRegisterTransferMobilePage')).toBeInTheDocument()
    expect(currentPath()).toBe('/cash/transfer')
  })

  it('sends /cash/transfer to /cash on a desktop', () => {
    renderAt('/cash/transfer', 'desktop')
    expect(currentPath()).toBe('/cash')
    expect(screen.getByText('CashPage')).toBeInTheDocument()
    expect(screen.queryByText('CashRegisterTransferMobilePage')).toBeNull()
  })

  it('keeps the desktop branch in Telegram WebApp at phone width', () => {
    window.Telegram = { WebApp: { initData: 'query_id=1', initDataUnsafe: {}, ready: () => undefined } }

    const first = renderAt('/cash', 'phone')
    expect(screen.getByText('CashPage')).toBeInTheDocument()
    expect(screen.queryByText('CashMobilePage')).toBeNull()
    first.unmount()

    renderAt('/cash/transfer', 'phone')
    expect(currentPath()).toBe('/cash')
    expect(screen.queryByText('CashRegisterTransferMobilePage')).toBeNull()
  })
})
