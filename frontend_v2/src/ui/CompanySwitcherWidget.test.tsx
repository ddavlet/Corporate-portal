import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { CompanyContextValue } from './company'

const { switchCompanyMock, companyState, actionItemsState } = vi.hoisted(() => ({
  switchCompanyMock: vi.fn(),
  companyState: { value: null as unknown as CompanyContextValue },
  actionItemsState: {
    value: { items: [] as unknown[], count: 0, loading: false, error: false },
  },
}))

vi.mock('./company', () => ({ useCompany: () => companyState.value }))
vi.mock('../lib/useActionItems', () => ({
  useActionItems: () => ({ ...actionItemsState.value, refresh: () => Promise.resolve() }),
}))

import { CompanySwitcherWidget } from './CompanySwitcherWidget'

const COMPANIES = [
  { subdomain: 'alpha', name: 'Альфа', action_items_count: 0 },
  { subdomain: 'beta', name: 'Бета', action_items_count: 5 },
]

function item(subdomain: string, id: number) {
  return { kind: 'request', id, tenant: { subdomain, name: subdomain } }
}

function options() {
  return Array.from(document.querySelectorAll('.ant-select-item-option'))
}

function option(name: string) {
  return options().find((el) => (el.textContent ?? '').includes(name))
}

async function openSwitcher() {
  fireEvent.mouseDown(screen.getByRole('combobox', { name: 'Компания' }))
  await waitFor(() => expect(options().length).toBeGreaterThan(0))
}

describe('CompanySwitcherWidget', () => {
  beforeEach(() => {
    companyState.value = {
      enabled: true,
      companies: COMPANIES,
      current: 'alpha',
      currentCompany: COMPANIES[0],
      switchCompany: switchCompanyMock,
    }
    actionItemsState.value = { items: [item('beta', 1), item('beta', 2), item('alpha', 3)], count: 3, loading: false, error: false }
  })

  it('renders nothing on a tenant subdomain', () => {
    companyState.value = { ...companyState.value, enabled: false, companies: [], current: null, currentCompany: null }
    render(<CompanySwitcherWidget />)
    expect(screen.queryByRole('combobox', { name: 'Компания' })).toBeNull()
  })

  it('shows the current company and lists every company with its live count', async () => {
    render(<CompanySwitcherWidget />)
    expect(screen.getByRole('combobox', { name: 'Компания' }).closest('.ant-select')).toHaveTextContent('Альфа')
    await openSwitcher()
    const beta = option('Бета')
    const alpha = option('Альфа')
    expect(beta).toHaveTextContent('Бета')
    // antd Badge shows its number as the counter's title.
    expect(beta?.querySelector('[title="2"]')).not.toBeNull()
    expect(alpha?.querySelector('[title="1"]')).not.toBeNull()
  })

  it('uses the counts of the company list until the action items load', async () => {
    actionItemsState.value = { items: [], count: 0, loading: true, error: false }
    render(<CompanySwitcherWidget />)
    await openSwitcher()
    const beta = option('Бета')
    expect(beta?.querySelector('[title="5"]')).not.toBeNull()
  })

  it('switches the company on pick', async () => {
    render(<CompanySwitcherWidget />)
    await openSwitcher()
    const beta = option('Бета')
    fireEvent.click(beta!)
    expect(switchCompanyMock).toHaveBeenCalledWith('beta')
  })
})
