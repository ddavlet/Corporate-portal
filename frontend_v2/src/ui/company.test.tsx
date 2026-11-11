import { useEffect } from 'react'
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { MyCompany } from '../lib/myCompaniesApi'

const { getMyCompaniesMock, logoutMock, resetSpy, portalState, notifyInfoMock, tenantLost } = vi.hoisted(() => ({
  getMyCompaniesMock: vi.fn(),
  logoutMock: vi.fn(),
  resetSpy: vi.fn(),
  portalState: { shared: true },
  notifyInfoMock: vi.fn(),
  tenantLost: {
    handler: null as null | ((code: 'tenant_forbidden' | 'tenant_required', sent: string | null) => boolean),
  },
}))

vi.mock('../lib/portalMode', () => ({ isSharedAppMode: () => portalState.shared }))
vi.mock('../lib/myCompaniesApi', () => ({ getMyCompanies: () => getMyCompaniesMock() }))
vi.mock('./auth', () => ({ useAuth: () => ({ logout: logoutMock }) }))
vi.mock('../lib/apiNotify', () => ({ notifyInfo: notifyInfoMock, notifyApiError: vi.fn(), notifyNetworkError: vi.fn() }))
vi.mock('../lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../lib/api')>()
  return {
    ...actual,
    setTenantAccessLostHandler: (handler: typeof tenantLost.handler) => {
      tenantLost.handler = handler
    },
  }
})
vi.mock('../lib/companyContext', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../lib/companyContext')>()
  return {
    ...actual,
    resetCompanyScopedState: () => {
      resetSpy()
      actual.resetCompanyScopedState()
    },
  }
})

import { CompanyProvider, pickCompany, useCompany } from './company'

const ALPHA: MyCompany = { subdomain: 'alpha', name: 'Альфа', action_items_count: 1 }
const BETA: MyCompany = { subdomain: 'beta', name: 'Бета', action_items_count: 0 }

const childRequests = vi.fn()

/** Stands for a page of the shell: asks the server on mount and saves its feed state on unmount, like RequestsPage. */
function Probe() {
  const { current, currentCompany, switchCompany, enabled } = useCompany()
  const location = useLocation()
  const navigate = useNavigate()
  useEffect(() => {
    childRequests(current)
    return () => {
      sessionStorage.setItem('list-session:/requests', JSON.stringify({ company: current }))
    }
  }, [current])
  return (
    <div>
      <div data-testid="where">{`${location.pathname}${location.search}`}</div>
      <div data-testid="company">{enabled ? `${current}|${currentCompany?.name ?? ''}` : 'subdomain'}</div>
      <button type="button" onClick={() => switchCompany('beta')}>
        В Бету
      </button>
      <button type="button" onClick={() => navigate(-1)}>
        Назад
      </button>
    </div>
  )
}

function renderProvider(path: string | string[] = '/requests') {
  const entries = Array.isArray(path) ? path : [path]
  return render(
    <MemoryRouter initialEntries={entries} initialIndex={entries.length - 1}>
      <Routes>
        <Route
          path="*"
          element={
            <CompanyProvider>
              <Probe />
            </CompanyProvider>
          }
        />
        <Route path="/login" element={<div>Страница входа</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('CompanyProvider', () => {
  beforeEach(() => {
    portalState.shared = true
    localStorage.clear()
    sessionStorage.clear()
    getMyCompaniesMock.mockReset()
    getMyCompaniesMock.mockResolvedValue([ALPHA, BETA])
    childRequests.mockReset()
    resetSpy.mockReset()
    notifyInfoMock.mockReset()
  })

  it('renders only its children on a tenant subdomain and asks for no companies', () => {
    portalState.shared = false
    renderProvider()
    expect(screen.getByTestId('company')).toHaveTextContent('subdomain')
    expect(getMyCompaniesMock).not.toHaveBeenCalled()
  })

  it('shows «Нет доступных компаний» with a sign-out button when the user has no company (crit. 11)', async () => {
    getMyCompaniesMock.mockResolvedValue([])
    renderProvider()
    expect(await screen.findByText('Нет доступных компаний')).toBeInTheDocument()
    expect(screen.queryByTestId('company')).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: /Выйти/ }))
    expect(logoutMock).toHaveBeenCalledTimes(1)
    expect(await screen.findByText('Страница входа')).toBeInTheDocument()
  })

  it('starts in the last saved company when it is still in the list (crit. 14)', async () => {
    localStorage.setItem('kolberg_v2_company_default', 'beta')
    renderProvider()
    expect(await screen.findByTestId('company')).toHaveTextContent('beta|Бета')
    expect(sessionStorage.getItem('kolberg_v2_company')).toBe('beta')
  })

  it('starts in the first company by name when the saved one is gone (crit. 14)', async () => {
    localStorage.setItem('kolberg_v2_company_default', 'gone')
    getMyCompaniesMock.mockResolvedValue([BETA, ALPHA])
    renderProvider()
    expect(await screen.findByTestId('company')).toHaveTextContent('alpha|Альфа')
  })

  it('prefers the company of this tab over the device default', async () => {
    localStorage.setItem('kolberg_v2_company_default', 'alpha')
    sessionStorage.setItem('kolberg_v2_company', 'beta')
    renderProvider()
    expect(await screen.findByTestId('company')).toHaveTextContent('beta|Бета')
  })

  it('switches the company: caches and saved feeds reset, start page opens (crit. 15)', async () => {
    renderProvider('/cash')
    expect(await screen.findByTestId('company')).toHaveTextContent('alpha|Альфа')
    expect(childRequests).toHaveBeenLastCalledWith('alpha')

    await userEvent.click(screen.getByRole('button', { name: 'В Бету' }))

    await waitFor(() => expect(screen.getByTestId('company')).toHaveTextContent('beta|Бета'))
    expect(screen.getByTestId('where')).toHaveTextContent(/^\/requests$/)
    expect(resetSpy).toHaveBeenCalledTimes(1)
    expect(sessionStorage.getItem('kolberg_v2_company')).toBe('beta')
    expect(localStorage.getItem('kolberg_v2_company_default')).toBe('beta')
    expect(childRequests).toHaveBeenLastCalledWith('beta')
    // The old page saved its feed while unmounting; that save must not leak into the new company.
    expect(sessionStorage.getItem('list-session:/requests')).toBeNull()
  })

  it('does not bring back an address of the previous company with «Back» after a switch', async () => {
    renderProvider(['/start', '/cash/5'])
    expect(await screen.findByTestId('company')).toHaveTextContent('alpha|Альфа')

    await userEvent.click(screen.getByRole('button', { name: 'В Бету' }))
    await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent(/^\/requests$/))

    await userEvent.click(screen.getByRole('button', { name: 'Назад' }))
    await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent(/^\/start$/))
    expect(screen.getByTestId('company')).toHaveTextContent('beta|Бета')
  })

  it('opens a deep link of another company in this tab only and says so', async () => {
    localStorage.setItem('kolberg_v2_company_default', 'alpha')
    sessionStorage.setItem('kolberg_v2_company', 'alpha')
    renderProvider('/requests/12?company=beta')
    await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent(/^\/requests\/12$/))
    expect(screen.getByTestId('company')).toHaveTextContent('beta|Бета')
    expect(sessionStorage.getItem('kolberg_v2_company')).toBe('beta')
    expect(localStorage.getItem('kolberg_v2_company_default')).toBe('alpha')
    expect(notifyInfoMock).toHaveBeenCalledWith('Вы перешли в компанию «Бета».')
  })

  it('moves to an available company when the server refuses this one (tenant_forbidden)', async () => {
    renderProvider('/requests/12')
    expect(await screen.findByTestId('company')).toHaveTextContent('alpha|Альфа')
    getMyCompaniesMock.mockResolvedValue([BETA])

    let handled = false
    act(() => {
      handled = tenantLost.handler?.('tenant_forbidden', 'alpha') ?? false
    })
    expect(handled).toBe(true)

    await waitFor(() => expect(screen.getByTestId('company')).toHaveTextContent('beta|Бета'))
    expect(screen.getByTestId('where')).toHaveTextContent(/^\/requests$/)
    expect(sessionStorage.getItem('kolberg_v2_company')).toBe('beta')
    expect(getMyCompaniesMock).toHaveBeenCalledTimes(2)
    expect(notifyInfoMock).toHaveBeenCalledWith('Нет доступа к прежней компании. Открыта компания «Бета».')

    // A late answer for the old company is swallowed and changes nothing.
    expect(tenantLost.handler?.('tenant_forbidden', 'alpha')).toBe(true)
    expect(getMyCompaniesMock).toHaveBeenCalledTimes(2)
  })

  it('shows «Нет доступных компаний» when the last company is gone', async () => {
    renderProvider()
    expect(await screen.findByTestId('company')).toHaveTextContent('alpha|Альфа')
    getMyCompaniesMock.mockResolvedValue([])
    act(() => {
      tenantLost.handler?.('tenant_forbidden', 'alpha')
    })
    expect(await screen.findByText('Нет доступных компаний')).toBeInTheDocument()
  })

  it('recovers a company only once when the server keeps refusing it (no reload loop)', async () => {
    getMyCompaniesMock.mockResolvedValue([ALPHA])
    renderProvider()
    expect(await screen.findByTestId('company')).toHaveTextContent('alpha|Альфа')

    act(() => {
      tenantLost.handler?.('tenant_forbidden', 'alpha')
    })
    await waitFor(() => expect(getMyCompaniesMock).toHaveBeenCalledTimes(2))
    expect(await screen.findByTestId('company')).toHaveTextContent('alpha|Альфа')

    expect(tenantLost.handler?.('tenant_forbidden', 'alpha')).toBe(false)
    expect(getMyCompaniesMock).toHaveBeenCalledTimes(2)
  })

  it('opens a deep link of my company in that company and drops the parameter (crit. 16)', async () => {
    renderProvider('/requests/12?company=beta&tab=files')
    await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent(/^\/requests\/12\?tab=files$/))
    expect(screen.getByTestId('company')).toHaveTextContent('beta|Бета')
    expect(sessionStorage.getItem('kolberg_v2_company')).toBe('beta')
    expect(childRequests).not.toHaveBeenCalledWith('alpha')
  })

  it('matches the company parameter case-insensitively (crit. 16)', async () => {
    renderProvider('/requests/12?company=BETA')
    await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent(/^\/requests\/12$/))
    expect(screen.getByTestId('company')).toHaveTextContent('beta|Бета')
  })

  it('keeps the parameter-free address as is for a link of the current company', async () => {
    sessionStorage.setItem('kolberg_v2_company', 'alpha')
    renderProvider('/requests/12?company=alpha')
    await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent(/^\/requests\/12$/))
    expect(screen.getByTestId('company')).toHaveTextContent('alpha|Альфа')
    expect(resetSpy).not.toHaveBeenCalled()
  })

  it('refuses a deep link of a foreign company without switching or loading anything (crit. 17)', async () => {
    sessionStorage.setItem('kolberg_v2_company', 'alpha')
    renderProvider('/requests/12?company=evil')
    expect(await screen.findByText('Нет доступа к компании')).toBeInTheDocument()
    expect(screen.queryByTestId('company')).toBeNull()
    expect(childRequests).not.toHaveBeenCalled()
    expect(sessionStorage.getItem('kolberg_v2_company')).toBe('alpha')

    await userEvent.click(screen.getByRole('button', { name: 'Перейти к заявкам' }))
    expect(await screen.findByTestId('company')).toHaveTextContent('alpha|Альфа')
    expect(screen.getByTestId('where')).toHaveTextContent(/^\/requests$/)
  })

  it('offers a retry when the company list fails to load', async () => {
    getMyCompaniesMock.mockRejectedValueOnce(new Error('offline'))
    renderProvider()
    expect(await screen.findByText('Не удалось загрузить список компаний')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Повторить' }))
    expect(await screen.findByTestId('company')).toHaveTextContent('alpha|Альфа')
  })
})

describe('pickCompany', () => {
  it('falls back from the tab to the default to the first by name', () => {
    expect(pickCompany([BETA, ALPHA], 'beta', 'alpha')).toBe('beta')
    expect(pickCompany([BETA, ALPHA], 'gone', 'beta')).toBe('beta')
    expect(pickCompany([BETA, ALPHA], null, null)).toBe('alpha')
    expect(pickCompany([], 'alpha', 'alpha')).toBeNull()
  })
})
