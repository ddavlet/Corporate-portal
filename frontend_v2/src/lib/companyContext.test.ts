import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createStorageMock } from '../test/helpers'

const { resetTenantAdminMock, resetReportTemplatesMock, resetActionItemsMock, portalState } = vi.hoisted(() => ({
  resetTenantAdminMock: vi.fn(),
  resetReportTemplatesMock: vi.fn(),
  resetActionItemsMock: vi.fn(),
  portalState: { shared: false },
}))

vi.mock('./useTenantAdmin', () => ({ resetTenantAdminCache: resetTenantAdminMock }))
vi.mock('./useReportTemplates', () => ({ resetReportTemplatesCache: resetReportTemplatesMock }))
vi.mock('./useActionItems', () => ({ resetActionItemsCache: resetActionItemsMock }))
vi.mock('./portalMode', () => ({ isSharedAppMode: () => portalState.shared }))

import {
  DEFAULT_COMPANY_KEY,
  TAB_COMPANY_KEY,
  clearTabCompany,
  getDefaultCompany,
  getTabCompany,
  resetCompanyScopedState,
  setTabCompany,
  setTabCompanyOnly,
} from './companyContext'

describe('companyContext', () => {
  const localStorageMock = createStorageMock()
  const sessionStorageMock = createStorageMock()

  beforeEach(() => {
    Object.defineProperty(globalThis, 'localStorage', { value: localStorageMock, configurable: true })
    Object.defineProperty(globalThis, 'sessionStorage', { value: sessionStorageMock, configurable: true })
    localStorageMock.clear()
    sessionStorageMock.clear()
    portalState.shared = false
    resetTenantAdminMock.mockReset()
    resetReportTemplatesMock.mockReset()
    resetActionItemsMock.mockReset()
  })

  it('sets only the tab company for a deep link and keeps the device default', () => {
    setTabCompany('acme')
    setTabCompanyOnly('beta')
    expect(getTabCompany()).toBe('beta')
    expect(getDefaultCompany()).toBe('acme')
  })

  it('keeps the action items of all companies on a switch on the shared app host', () => {
    portalState.shared = true
    sessionStorageMock.setItem('list-session:/requests', '{"scrollY":120}')
    resetCompanyScopedState()
    expect(resetActionItemsMock).not.toHaveBeenCalled()
    expect(resetTenantAdminMock).toHaveBeenCalledTimes(1)
    expect(resetReportTemplatesMock).toHaveBeenCalledTimes(1)
    expect(sessionStorageMock.getItem('list-session:/requests')).toBeNull()
  })

  it('keeps the tab company in sessionStorage and the device default in localStorage', () => {
    expect(getTabCompany()).toBeNull()
    setTabCompany('acme')
    expect(sessionStorageMock.getItem(TAB_COMPANY_KEY)).toBe('acme')
    expect(localStorageMock.getItem(DEFAULT_COMPANY_KEY)).toBe('acme')
    expect(getTabCompany()).toBe('acme')
    expect(getDefaultCompany()).toBe('acme')
  })

  it('clears only the tab company on logout', () => {
    setTabCompany('acme')
    clearTabCompany()
    expect(getTabCompany()).toBeNull()
    expect(getDefaultCompany()).toBe('acme')
  })

  it('gives each tab its own company while the default is shared (two tabs)', () => {
    const otherTab = createStorageMock()
    setTabCompany('acme')
    Object.defineProperty(globalThis, 'sessionStorage', { value: otherTab, configurable: true })
    expect(getTabCompany()).toBeNull()
    setTabCompany('beta')
    expect(getTabCompany()).toBe('beta')
    Object.defineProperty(globalThis, 'sessionStorage', { value: sessionStorageMock, configurable: true })
    expect(getTabCompany()).toBe('acme')
    expect(getDefaultCompany()).toBe('beta')
  })

  it('resets the module caches and removes only list and report session keys', () => {
    sessionStorageMock.setItem('list-session:/requests', '{"scrollY":120}')
    sessionStorageMock.setItem('list-session:/cash/all', '{"scrollY":0}')
    sessionStorageMock.setItem('reports.view.pnl.summary', '?month=2026-10')
    sessionStorageMock.setItem(TAB_COMPANY_KEY, 'acme')
    sessionStorageMock.setItem('kolberg_v2_tg_tokens', '{"access":"a","refresh":"r"}')
    sessionStorageMock.setItem('tg_oidc_state', 'x')

    resetCompanyScopedState()

    expect(resetTenantAdminMock).toHaveBeenCalledTimes(1)
    expect(resetReportTemplatesMock).toHaveBeenCalledTimes(1)
    expect(resetActionItemsMock).toHaveBeenCalledTimes(1)
    expect(sessionStorageMock.getItem('list-session:/requests')).toBeNull()
    expect(sessionStorageMock.getItem('list-session:/cash/all')).toBeNull()
    expect(sessionStorageMock.getItem('reports.view.pnl.summary')).toBeNull()
    expect(sessionStorageMock.getItem(TAB_COMPANY_KEY)).toBe('acme')
    expect(sessionStorageMock.getItem('kolberg_v2_tg_tokens')).not.toBeNull()
    expect(sessionStorageMock.getItem('tg_oidc_state')).toBe('x')
  })
})
