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

  it('does not let clicks inside the edit modal bubble to an ancestor row click handler', async () => {
    // Regression test: antd Modal renders via a React portal into document.body,
    // but React still bubbles its synthetic click events through the *component*
    // tree. A table row with `onRow: { onClick }` is a component-tree ancestor of
    // this button's modal, so any click inside the modal (e.g. its Cancel/OK
    // buttons) used to also fire the row's onClick and reopen whatever it opens.
    mockState.isAdmin = true
    const rowClick = vi.fn()
    render(
      <div onClick={rowClick}>
        <AdminEditRecordButton endpoint="/api/requests/" record={{ id: 1, title: 'Заявка' }} onSaved={() => undefined} />
      </div>,
    )

    fireEvent.click(screen.getByRole('button', { name: /Редактировать/ }))
    await screen.findByRole('button', { name: 'Сохранить' })
    expect(rowClick).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(rowClick).not.toHaveBeenCalled()
  })
})
