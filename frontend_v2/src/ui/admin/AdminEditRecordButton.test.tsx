import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AdminEditRecordButton } from './AdminEditRecordButton'

// Mutable holder created via vi.hoisted so it is safely initialized before the
// hoisted vi.mock factory runs.
const mockState = vi.hoisted(() => ({ isAdmin: false, loading: false }))

vi.mock('../../lib/useTenantAdmin', () => ({
  useTenantAdmin: () => mockState,
}))

// AdminRecordEditModal pulls in apiFetch; stub it so no real network module loads.
vi.mock('../../lib/api', () => ({
  apiFetch: vi.fn(),
}))

describe('AdminEditRecordButton', () => {
  afterEach(() => {
    mockState.isAdmin = false
    mockState.loading = false
  })

  it('renders nothing for non-admins', () => {
    mockState.isAdmin = false
    const { container } = render(
      <AdminEditRecordButton endpoint="/api/requests/" record={{ id: 1 }} onSaved={() => undefined} />,
    )
    expect(container).toBeEmptyDOMElement()
  })

  it('shows the edit button for admins and opens the edit modal', async () => {
    mockState.isAdmin = true
    render(
      <AdminEditRecordButton endpoint="/api/requests/" record={{ id: 1, title: 'Заявка' }} onSaved={() => undefined} />,
    )

    const button = screen.getByRole('button', { name: /Редактировать/ })
    fireEvent.click(button)

    // The modal's save button confirms the editor opened.
    expect(await screen.findByRole('button', { name: 'Сохранить' })).toBeInTheDocument()
  })
})
