import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AdminEditRecordButton } from './AdminEditRecordButton'

let adminState = { isAdmin: false, loading: false }

vi.mock('../../lib/useTenantAdmin', () => ({
  useTenantAdmin: () => adminState,
}))

// AdminRecordEditModal pulls in apiFetch; stub it so the module loads without network.
vi.mock('../../lib/api', () => ({
  apiFetch: vi.fn(),
}))

describe('AdminEditRecordButton', () => {
  afterEach(() => {
    adminState = { isAdmin: false, loading: false }
  })

  it('renders nothing for non-admins', () => {
    adminState = { isAdmin: false, loading: false }
    const { container } = render(
      <AdminEditRecordButton endpoint="/api/requests/" record={{ id: 1 }} onSaved={() => undefined} />,
    )
    expect(container).toBeEmptyDOMElement()
  })

  it('shows the edit button for admins and opens the edit modal', () => {
    adminState = { isAdmin: true, loading: false }
    render(
      <AdminEditRecordButton endpoint="/api/requests/" record={{ id: 1, title: 'Заявка' }} onSaved={() => undefined} />,
    )

    const button = screen.getByRole('button', { name: /Редактировать/ })
    expect(button).toBeTruthy()

    fireEvent.click(button)
    // Modal save button confirms the editor opened
    expect(screen.getByRole('button', { name: 'Сохранить' })).toBeTruthy()
  })
})
