import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AppShell } from './AppShell'
import { installViewport } from '../test/viewport'

// The desktop layout (ProLayout); the phone layout is covered in MobileAppShell.test.tsx.
installViewport('desktop')

let actionItemsCount = 0

vi.mock('../lib/useActionItems', () => ({
  useActionItems: () => ({
    items: [],
    count: actionItemsCount,
    loading: false,
    error: false,
    refresh: () => Promise.resolve(),
  }),
}))

vi.mock('../lib/api', () => ({
  getSettingsAccess: () =>
    Promise.resolve({ tenant_name: 'Тестовая компания', can_open_settings: false, can_open_admin: false }),
  changePassword: vi.fn(),
}))

vi.mock('./auth', () => ({
  useAuth: () => ({ logout: vi.fn(), username: 'ivan' }),
}))

const SUBDOMAIN_COMPANY = {
  enabled: false,
  companies: [] as { subdomain: string; name: string; action_items_count: number }[],
  current: null as string | null,
  currentCompany: null as { subdomain: string; name: string; action_items_count: number } | null,
  switchCompany: vi.fn(),
}
let companyValue = SUBDOMAIN_COMPANY

vi.mock('./company', () => ({
  useCompany: () => companyValue,
}))

vi.mock('./moduleAccess', () => ({
  useModuleAccess: () => ({ hasAccess: () => true }),
}))

function renderShell(path = '/') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/" element={<AppShell />}>
          <Route index element={<div>Панель-заглушка</div>} />
          <Route path="notifications" element={<div>Страница уведомлений</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  )
}

/** antd Badge exposes the shown number as the title of its counter. */
function badgeCounters(count: number) {
  return screen.queryAllByTitle(String(count))
}

describe('AppShell notifications badges', () => {
  beforeEach(() => {
    actionItemsCount = 0
    companyValue = SUBDOMAIN_COMPANY
  })

  it('shows the count on the menu item and on the bell', async () => {
    actionItemsCount = 4
    renderShell()
    expect(await screen.findByRole('button', { name: 'Уведомления: требуется действие (4)' })).toBeInTheDocument()
    expect(screen.getAllByText('Уведомления').length).toBeGreaterThan(0)
    await waitFor(() => expect(badgeCounters(4)).toHaveLength(2))
  })

  it('shows no badge at zero', async () => {
    renderShell()
    expect(await screen.findByRole('button', { name: 'Уведомления' })).toBeInTheDocument()
    expect(screen.getAllByText('Уведомления').length).toBeGreaterThan(0)
    expect(badgeCounters(0)).toHaveLength(0)
    expect(screen.queryAllByTitle(/^\d+\+?$/)).toHaveLength(0)
  })

  it('opens the notifications page from the bell', async () => {
    actionItemsCount = 2
    renderShell()
    await userEvent.click(await screen.findByRole('button', { name: 'Уведомления: требуется действие (2)' }))
    expect(await screen.findByText('Страница уведомлений')).toBeInTheDocument()
  })
})

describe('AppShell company switcher', () => {
  beforeEach(() => {
    actionItemsCount = 0
    companyValue = SUBDOMAIN_COMPANY
  })

  it('has no company switcher on a tenant subdomain', async () => {
    renderShell()
    expect(await screen.findByRole('button', { name: 'Уведомления' })).toBeInTheDocument()
    expect(screen.queryByRole('combobox', { name: 'Компания' })).toBeNull()
  })

  it('shows the company switcher on the shared app host', async () => {
    const alpha = { subdomain: 'alpha', name: 'Альфа', action_items_count: 0 }
    companyValue = {
      ...SUBDOMAIN_COMPANY,
      enabled: true,
      companies: [alpha, { subdomain: 'beta', name: 'Бета', action_items_count: 2 }],
      current: 'alpha',
      currentCompany: alpha,
    }
    renderShell()
    const switcher = await screen.findByRole('combobox', { name: 'Компания' })
    expect(switcher.closest('.ant-select')).toHaveTextContent('Альфа')
  })
})
