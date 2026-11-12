import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { resetViewport, setViewport, type ViewportKind } from '../../test/viewport'
import type { RequestDetail } from '../requests/RequestDetailModal'
import { TgRequestDetailPage } from './TgRequestDetailPage'

// Regression: the Telegram Mini App keeps its own markup (tg-* classes) at any width; the portal's phone card
// (.m-bottom-bar, request-detail-mobile) must never take over /tg/requests/:id.

const api = vi.hoisted(() => ({ apiFetch: vi.fn(), getRequestFormOptions: vi.fn() }))

vi.mock('../../lib/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../lib/api')>()),
  apiFetch: (...args: unknown[]) => api.apiFetch(...args),
  getRequestFormOptions: (...args: unknown[]) => api.getRequestFormOptions(...args),
}))

vi.mock('../../lib/useActionItems', () => ({
  refreshActionItems: () => Promise.resolve(),
  useActionItems: () => ({ items: [], count: 0, loading: false, error: false, refresh: vi.fn() }),
}))

vi.mock('../auth', () => ({
  useAuth: () => ({ accessToken: `header.${btoa(JSON.stringify({ user_id: 7 })).replace(/=+$/, '')}.signature` }),
}))

const detail: RequestDetail = {
  id: 77,
  title: 'Аренда офиса',
  description: '',
  amount: 2500000,
  currency: 'UZS',
  status: '1',
  urgency: 'Обычно',
  payment_type: 'Перечисление',
  category: 'Аренда',
  vendor: 'ООО Альфа',
  requester: 3,
  submitted_at: '2026-11-09T09:05:00Z',
  billing_date: '2026-11-01',
  // The signed-in user's own active step: on the portal's phone card this would show the decision bar.
  approvals: [{ id: 21, step: 1, step_type: 'approval', decision: 'pending', approver_user: 7, approver_username: 'me' }],
  comments: [],
}

function renderTgPage() {
  return render(
    <MemoryRouter initialEntries={['/tg/requests/77']}>
      <Routes>
        <Route path="/tg/requests/:id" element={<TgRequestDetailPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe.each<ViewportKind>(['phone', 'desktop'])('TgRequestDetailPage on a %s', (viewport) => {
  beforeEach(() => {
    setViewport(viewport)
    api.apiFetch.mockReset().mockImplementation(async (url: string) =>
      new Response(JSON.stringify(url === '/api/requests/77/' ? detail : {}), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    api.getRequestFormOptions.mockReset().mockResolvedValue({ is_tenant_admin: false })
  })

  afterEach(() => {
    resetViewport()
  })

  it('keeps the Mini App markup and never shows the portal phone card', async () => {
    const { container } = renderTgPage()

    await waitFor(() => expect(container.querySelector('.tg-detail-hero')).not.toBeNull())
    expect(container.querySelector('.tg-detail-card')).not.toBeNull()
    expect(container.querySelector('.tg-actions-stack')).not.toBeNull()
    expect(document.querySelector('.m-bottom-bar')).toBeNull()
    expect(screen.queryByTestId('request-detail-mobile')).toBeNull()
    // The Mini App's own approval buttons are still there.
    expect(screen.getByRole('button', { name: 'Одобрить' })).toBeInTheDocument()
  })
})
