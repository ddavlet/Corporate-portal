import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { CashMobilePage } from './CashMobilePage'
import { createMobileHeaderStore, MobileShellContext, type MobileHeaderStore } from './mobileShell'

const access = vi.hoisted(() => ({
  value: { loading: false, hasAccess: (_key: string): boolean => true } as {
    loading: boolean
    hasAccess: (key: string) => boolean
  },
}))

vi.mock('./moduleAccess', () => ({
  useModuleAccess: () => access.value,
}))

function LocationProbe() {
  const location = useLocation()
  return <div data-testid="location">{location.pathname}</div>
}

function renderPage(store: MobileHeaderStore | null = null) {
  return render(
    <MobileShellContext.Provider
      value={{ userId: 1, userIdStatus: 'ready', openCompanySwitcher: () => undefined, headerStore: store }}
    >
      <MemoryRouter initialEntries={['/cash']}>
        <Routes>
          <Route path="/cash" element={<CashMobilePage />} />
          <Route path="/cash/transfer" element={<div>Форма перевода</div>} />
        </Routes>
        <LocationProbe />
      </MemoryRouter>
    </MobileShellContext.Provider>,
  )
}

beforeEach(() => {
  access.value = { loading: false, hasAccess: () => true }
})

describe('CashMobilePage', () => {
  it('sets the header and shows only the transfer action, without lists or hints', () => {
    const store = createMobileHeaderStore()
    const { container } = renderPage(store)

    expect(store.get()).toMatchObject({ title: 'Касса' })
    expect(screen.getAllByRole('button')).toHaveLength(1)
    expect(screen.getByRole('button', { name: /Перевести между кассами/ })).toBeInTheDocument()
    expect(container.querySelector('.ant-table')).toBeNull()
    expect(screen.queryByText(/компьютер/)).toBeNull()
  })

  it('opens the transfer form', () => {
    renderPage()
    fireEvent.click(screen.getByRole('button', { name: /Перевести между кассами/ }))
    expect(screen.getByTestId('location').textContent).toBe('/cash/transfer')
    expect(screen.getByText('Форма перевода')).toBeInTheDocument()
  })

  it('shows an empty state without access to the module', () => {
    access.value = { loading: false, hasAccess: (key) => key !== 'cash' }
    renderPage()
    expect(screen.getByText('Раздел недоступен')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Перевести между кассами/ })).toBeNull()
  })

  it('shows the loading state while the modules load', () => {
    access.value = { loading: true, hasAccess: () => false }
    renderPage()
    expect(screen.getByTestId('mobile-state-loading')).toBeInTheDocument()
    expect(screen.queryByText('Раздел недоступен')).toBeNull()
  })
})
