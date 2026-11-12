import { useSyncExternalStore } from 'react'
import dayjs from 'dayjs'
import timezone from 'dayjs/plugin/timezone'
import utc from 'dayjs/plugin/utc'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { message, theme } from 'antd'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MobileShellContext, createMobileHeaderStore, type MobileHeaderStore } from '../mobileShell'
import { contrastRatio } from '../../test/contrast'
import { resetViewport, setViewport } from '../../test/viewport'
import type { ApprovalItem, RequestDetail } from './RequestDetailModal'
import { RequestDetailPage } from './RequestDetailPage'

// main.tsx extends dayjs in the app; the draft edit modal needs .tz() (tashkentTime).
dayjs.extend(utc)
dayjs.extend(timezone)

const api = vi.hoisted(() => ({
  apiFetch: vi.fn(),
  getRequestFormOptions: vi.fn(),
  setRequestApprovalDecision: vi.fn(),
  confirmPaymentViaWebApp: vi.fn(),
  resendApprovalCard: vi.fn(),
  copyPortalRequest: vi.fn(),
  submitRequestForApproval: vi.fn(),
}))

vi.mock('../../lib/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../lib/api')>()),
  apiFetch: (...args: unknown[]) => api.apiFetch(...args),
  getRequestFormOptions: (...args: unknown[]) => api.getRequestFormOptions(...args),
  setRequestApprovalDecision: (...args: unknown[]) => api.setRequestApprovalDecision(...args),
  confirmPaymentViaWebApp: (...args: unknown[]) => api.confirmPaymentViaWebApp(...args),
  resendApprovalCard: (...args: unknown[]) => api.resendApprovalCard(...args),
  copyPortalRequest: (...args: unknown[]) => api.copyPortalRequest(...args),
  submitRequestForApproval: (...args: unknown[]) => api.submitRequestForApproval(...args),
}))

const refreshActionItems = vi.hoisted(() => vi.fn())
vi.mock('../../lib/useActionItems', () => ({
  refreshActionItems: () => refreshActionItems(),
  useActionItems: () => ({ items: [], count: 0, loading: false, error: false, refresh: refreshActionItems }),
}))

vi.mock('../../lib/portalMode', () => ({ isSharedAppMode: () => false }))

// The real comments section, plus a probe of the antd theme it is rendered in (secondary text colour and the height of
// small buttons): jsdom does not compute antd's CSS-in-JS styles.
vi.mock('./RequestCommentsSection', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./RequestCommentsSection')>()
  const React = await import('react')
  const { ConfigProvider, theme: antdTheme } = await import('antd')
  function CommentsThemeProbe() {
    const { token } = antdTheme.useToken()
    const config = React.useContext(ConfigProvider.ConfigContext)
    return React.createElement('span', {
      'data-testid': 'comments-theme',
      'data-text-description': token.colorTextDescription,
      'data-button-height-sm': String(config.theme?.components?.Button?.controlHeightSM ?? ''),
    })
  }
  return {
    ...actual,
    RequestCommentsSection: (props: Parameters<typeof actual.RequestCommentsSection>[0]) =>
      React.createElement(
        React.Fragment,
        null,
        React.createElement(CommentsThemeProbe),
        React.createElement(actual.RequestCommentsSection, props),
      ),
  }
})

const token = theme.getDesignToken()

const ME = 7

/** An access token whose payload carries the signed-in user's id (the page reads `user_id` from it). */
function tokenFor(userId: number): string {
  const payload = btoa(JSON.stringify({ user_id: userId })).replace(/=+$/, '')
  return `header.${payload}.signature`
}

vi.mock('../auth', () => ({ useAuth: () => ({ accessToken: tokenFor(7) }) }))

function approval(overrides: Partial<ApprovalItem>): ApprovalItem {
  return {
    id: 1,
    step: 1,
    step_type: 'approval',
    decision: 'approved',
    approver_user: 3,
    approver_username: 'petrov',
    decided_at: '2026-11-10T09:00:00Z',
    ...overrides,
  }
}

function makeDetail(overrides: Partial<RequestDetail> = {}): RequestDetail {
  return {
    id: 77,
    title: 'Аренда офиса за ноябрь',
    description: 'Оплата по договору аренды',
    amount: 2500000,
    currency: 'UZS',
    status: '2',
    urgency: 'Обычно',
    payment_type: 'Перечисление',
    category: 'Аренда',
    vendor: 'ООО Альфа',
    payment_purpose: 'Аренда',
    company_payer: 'Kolberg',
    requester: 3,
    requester_username: 'petrov',
    created_at: '2026-11-09T09:00:00Z',
    submitted_at: '2026-11-09T09:05:00Z',
    billing_date: '2026-11-01',
    attachments: [
      { id: 5, name: 'Счёт.pdf', content_type: 'application/pdf', size_bytes: 1000, url: '/api/files/download/?path=a.pdf' },
    ],
    approvals: [
      approval({ id: 1, step: 1, decision: 'approved', comment: 'Ок' }),
      approval({ id: 2, step: 2, decision: 'pending', approver_user: ME, approver_username: 'me', decided_at: null }),
      approval({ id: 3, step: 3, step_type: 'payment', decision: 'pending', approver_user: 4, approver_username: 'cashier', decided_at: null }),
    ],
    comments: [],
    ...overrides,
  }
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

let currentDetail: RequestDetail = makeDetail()

function HeaderProbe({ store }: { store: MobileHeaderStore }) {
  const config = useSyncExternalStore(store.subscribe, store.get, store.get)
  return (
    <div data-testid="header">
      <span data-testid="header-title">{config?.title}</span>
      {config?.action}
    </div>
  )
}

function renderPage(path = '/requests/77') {
  const headerStore = createMobileHeaderStore()
  return render(
    <MobileShellContext.Provider
      value={{ userId: ME, userIdStatus: 'ready', openCompanySwitcher: vi.fn(), headerStore }}
    >
      <MemoryRouter initialEntries={[path]}>
        <HeaderProbe store={headerStore} />
        <Routes>
          <Route path="/requests/:id" element={<RequestDetailPage />} />
        </Routes>
      </MemoryRouter>
    </MobileShellContext.Provider>,
  )
}

async function openMenu() {
  fireEvent.click(within(screen.getByTestId('header')).getByRole('button', { name: 'Действия с заявкой' }))
  return screen.findByRole('list', { name: 'Действия с заявкой' })
}

describe('RequestDetailPage on a phone', () => {
  beforeEach(() => {
    setViewport('phone')
    currentDetail = makeDetail()
    Object.values(api).forEach((fn) => fn.mockReset())
    refreshActionItems.mockReset().mockResolvedValue(undefined)
    api.apiFetch.mockImplementation(async (url: string) =>
      url === '/api/requests/77/' ? jsonResponse(currentDetail) : jsonResponse({}),
    )
    api.getRequestFormOptions.mockResolvedValue({ is_tenant_admin: false })
    api.setRequestApprovalDecision.mockResolvedValue(undefined)
    vi.spyOn(message, 'success').mockImplementation(() => undefined as never)
    vi.spyOn(message, 'error').mockImplementation(() => undefined as never)
  })

  afterEach(() => {
    resetViewport()
    vi.restoreAllMocks()
  })

  it('shows the hero, fields over values, files, the approvals timeline and comments without the bordered table', async () => {
    const { container } = renderPage()

    expect(await screen.findByTestId('request-detail-mobile')).toBeInTheDocument()
    expect(container.querySelector('.ant-descriptions-bordered')).toBeNull()
    expect(screen.getByTestId('header-title')).toHaveTextContent('Заявка #77')
    expect(screen.getByText('Шаг 2 из 3')).toBeInTheDocument()
    expect(screen.getByText('Аренда офиса за ноябрь')).toBeInTheDocument()
    expect(screen.getByText('2 500 000 UZS')).toBeInTheDocument()

    const fields = screen.getByTestId('request-fields')
    expect(within(fields).getByText('Тип оплаты')).toBeInTheDocument()
    expect(within(fields).getByText('Перечисление')).toBeInTheDocument()

    expect(within(screen.getByRole('list', { name: 'Файлы' })).getByRole('button', { name: /Счёт\.pdf/ })).toBeInTheDocument()

    const timeline = screen.getByTestId('request-approvals-timeline')
    expect(within(timeline).getByText('Шаг 3 · выплата')).toBeInTheDocument()
    expect(within(screen.getByTestId('approval-1')).getByText('Ок')).toBeInTheDocument()
    expect(within(screen.getByTestId('approval-1')).getByText(/Одобрено/)).toBeInTheDocument()

    expect(screen.getByText('Комментарии')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '+ Добавить' })).toBeInTheDocument()
  })

  it('shows the plaque and the decision bar only on the user’s own active step', async () => {
    renderPage()

    expect(await screen.findByTestId('awaiting-my-decision')).toHaveTextContent('Ждёт вашего решения')
    const bar = screen.getByTestId('request-decision-bar')
    const approve = within(bar).getByRole('button', { name: 'Одобрить' })
    const reject = within(bar).getByRole('button', { name: 'Отклонить' })
    // Touch targets of the bar.
    expect(approve).toHaveStyle({ height: '44px' })
    expect(reject).toHaveStyle({ height: '44px' })
  })

  it('shows no plaque and no bar when the active step belongs to someone else', async () => {
    currentDetail = makeDetail({
      approvals: [
        approval({ id: 1, step: 1, decision: 'approved' }),
        approval({ id: 2, step: 2, decision: 'pending', approver_user: 99, approver_username: 'other', decided_at: null }),
        // The user's step comes later: it is not active yet.
        approval({ id: 3, step: 3, decision: 'pending', approver_user: ME, decided_at: null }),
      ],
    })
    renderPage()

    expect(await screen.findByTestId('request-detail-mobile')).toBeInTheDocument()
    expect(screen.queryByTestId('awaiting-my-decision')).toBeNull()
    expect(screen.queryByTestId('request-decision-bar')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Одобрить' })).toBeNull()
    expect(screen.getByText('Сейчас на шаге 2.')).toBeInTheDocument()
  })

  it('approves the step, then refreshes the card and the action items', async () => {
    renderPage()

    const bar = await screen.findByTestId('request-decision-bar')
    currentDetail = makeDetail({
      status: '3',
      approvals: currentDetail.approvals.map((a) => (a.id === 2 ? { ...a, decision: 'approved' } : a)),
    })
    fireEvent.click(within(bar).getByRole('button', { name: 'Одобрить' }))

    await waitFor(() =>
      expect(api.setRequestApprovalDecision).toHaveBeenCalledWith({ requestId: 77, step: 2, decision: 'approved' }),
    )
    await waitFor(() => expect(refreshActionItems).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(screen.queryByTestId('request-decision-bar')).toBeNull())
    expect(api.apiFetch.mock.calls.filter(([url]) => url === '/api/requests/77/')).toHaveLength(2)
  })

  it('has no buttons on a notification step', async () => {
    currentDetail = makeDetail({
      approvals: [approval({ id: 2, step: 1, step_type: 'notification', decision: 'pending', approver_user: ME, decided_at: null })],
      status: '1',
    })
    renderPage()

    expect(await screen.findByTestId('notification-step-note')).toBeInTheDocument()
    expect(screen.queryByTestId('request-decision-bar')).toBeNull()
    expect(screen.queryByTestId('awaiting-my-decision')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Одобрить' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Отклонить' })).toBeNull()
  })

  it('points to the bot on a payment step confirmed by callback', async () => {
    currentDetail = makeDetail({
      status: '1',
      approvals: [
        approval({ id: 4, step: 1, step_type: 'payment', payment_action_mode: 'callback', decision: 'pending', approver_user: ME, decided_at: null }),
      ],
    })
    renderPage()

    expect(await screen.findByTestId('awaiting-my-decision')).toHaveTextContent('через Telegram-бота')
    const bar = screen.getByTestId('request-decision-bar')
    expect(within(bar).queryByRole('button', { name: 'Подтвердить выплату' })).toBeNull()
    expect(within(bar).getByRole('button', { name: 'Отклонить' })).toBeInTheDocument()
  })

  it('offers «Подтвердить выплату» on a payment step confirmed in the web app', async () => {
    currentDetail = makeDetail({
      status: '1',
      approvals: [
        approval({ id: 4, step: 1, step_type: 'payment', payment_action_mode: 'webapp', decision: 'pending', approver_user: ME, decided_at: null }),
      ],
    })
    renderPage()

    const bar = await screen.findByTestId('request-decision-bar')
    expect(within(bar).getByRole('button', { name: 'Подтвердить выплату' })).toBeInTheDocument()
    expect(within(bar).queryByRole('button', { name: 'Одобрить' })).toBeNull()
  })

  it('lists the draft actions, a note and a copy in the «⋯» menu, without admin editing', async () => {
    currentDetail = makeDetail({ status: 'DRAFT', requester: ME, approvals: [] })
    renderPage()
    await screen.findByTestId('request-detail-mobile')

    const menu = await openMenu()
    const items = within(menu).getAllByRole('button').map((b) => b.textContent)
    expect(items).toEqual([
      'Редактировать черновик',
      'Отправить на согласование',
      'Прикрепить файл',
      'Добавить заметку',
      'Копировать заявку',
    ])

    fireEvent.click(within(menu).getByRole('button', { name: 'Редактировать черновик' }))
    await waitFor(() => expect(document.querySelector('.ant-modal-title')).toHaveTextContent('Редактировать черновик'))
  })

  it('shows only a note and a copy for someone else’s request', async () => {
    renderPage()
    await screen.findByTestId('request-detail-mobile')

    const menu = await openMenu()
    expect(within(menu).getAllByRole('button').map((b) => b.textContent)).toEqual(['Добавить заметку', 'Копировать заявку'])
  })

  it('resends the approval card from its sheet and keeps the cooldown', async () => {
    const inAMinute = new Date(Date.now() + 60_000).toISOString()
    currentDetail = makeDetail({
      approvals: [
        approval({ id: 1, step: 1, decision: 'approved' }),
        approval({ id: 2, step: 2, decision: 'pending', approver_user: 99, approver_username: 'other', decided_at: null, can_resend: true, resend_count: 1 }),
        approval({ id: 3, step: 2, decision: 'pending', approver_user: 98, approver_username: 'third', decided_at: null, can_resend: true, resend_available_at: inAMinute }),
      ],
    })
    api.resendApprovalCard.mockResolvedValue(undefined)
    renderPage()
    await screen.findByTestId('request-detail-mobile')

    const menu = await openMenu()
    fireEvent.click(within(menu).getByRole('button', { name: 'Переотправить согласование' }))

    const ready = await screen.findByTestId('resend-approval-2')
    const cooling = screen.getByTestId('resend-approval-3')
    expect(within(cooling).getByRole('button', { name: /Подождите \d+с/ })).toBeDisabled()

    fireEvent.click(within(ready).getByRole('button', { name: /Переотправить \(2 из 3\)/ }))
    await waitFor(() => expect(api.resendApprovalCard).toHaveBeenCalledWith(77, 2))
  })

  it('flags a paid request without a linked expense in dark red, at 4.5:1 or more', async () => {
    currentDetail = makeDetail({ status: 'PAYED', approvals: [], expense_link: null })
    renderPage()

    const note = await screen.findByTestId('payed-no-expense-note')
    expect(note).toHaveTextContent('Оплачена, но расход не найден')
    expect(note.style.color).not.toBe('')
    expect(contrastRatio(note.style.color)).toBeGreaterThanOrEqual(4.5)
  })

  it('writes the hero status tag at 4.5:1 or more on its fill', async () => {
    currentDetail = makeDetail({ status: 'REJECTED', approvals: [] })
    renderPage()

    await screen.findByTestId('request-detail-mobile')
    const tag = screen.getByText('Отклонена')
    expect(contrastRatio(tag.style.color, tag.style.backgroundColor)).toBeGreaterThanOrEqual(4.5)
  })

  it('renders the comments in the phone theme: 44 px small buttons and darker secondary text', async () => {
    renderPage()

    await screen.findByTestId('request-detail-mobile')
    const probe = within(screen.getByRole('region', { name: 'Комментарии' })).getByTestId('comments-theme')
    expect(probe).toHaveAttribute('data-button-height-sm', '44')
    expect(probe).toHaveAttribute('data-text-description', token.colorTextSecondary)
    expect(contrastRatio(token.colorTextSecondary)).toBeGreaterThanOrEqual(4.5)
  })

  it('marks «Отправить на согласование» as busy and unavailable while the draft is being sent', async () => {
    currentDetail = makeDetail({ status: 'DRAFT', requester: ME, approvals: [] })
    api.submitRequestForApproval.mockReturnValue(new Promise(() => undefined))
    renderPage()
    await screen.findByTestId('request-detail-mobile')

    fireEvent.click(within(await openMenu()).getByRole('button', { name: 'Отправить на согласование' }))
    await waitFor(() => expect(api.submitRequestForApproval).toHaveBeenCalledWith(77))

    const row = within(await openMenu()).getByRole('button', { name: 'Отправить на согласование' })
    expect(row).toBeDisabled()
    expect(row).toHaveAttribute('aria-busy', 'true')
  })

  it('offers resending the payment step of an APPROVED request', async () => {
    currentDetail = makeDetail({
      status: 'APPROVED',
      approvals: [
        approval({ id: 1, step: 1, decision: 'approved' }),
        approval({
          id: 5,
          step: 2,
          step_type: 'payment',
          decision: 'pending',
          approver_user: 99,
          approver_username: 'cashier',
          decided_at: null,
          can_resend: true,
        }),
      ],
    })
    renderPage()
    await screen.findByTestId('request-detail-mobile')

    fireEvent.click(within(await openMenu()).getByRole('button', { name: 'Переотправить согласование' }))
    expect(await screen.findByTestId('resend-approval-5')).toHaveTextContent('Шаг 2 · cashier')
  })

  it('does not flag a paid request whose expense is a cash record', async () => {
    currentDetail = makeDetail({ status: 'PAYED', approvals: [], expense_link: { module: 'cash', id: 5 } })
    renderPage()

    await screen.findByTestId('request-detail-mobile')
    expect(screen.queryByTestId('payed-no-expense-note')).toBeNull()
  })

  it('shows «Файлов нет» when the request has no attachments', async () => {
    currentDetail = makeDetail({ attachments: [] })
    renderPage()

    await screen.findByTestId('request-detail-mobile')
    expect(screen.getByText('Файлов нет')).toBeInTheDocument()
    expect(screen.queryByRole('list', { name: 'Файлы' })).toBeNull()
  })

  it('shows an error with «Повторить» when the request cannot be loaded', async () => {
    api.apiFetch.mockImplementation(async () => jsonResponse({ detail: 'Не найдено' }, 404))
    renderPage()

    expect(await screen.findByTestId('mobile-state-error')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Повторить/ })).toBeInTheDocument()
  })
})

describe('RequestDetailPage on a desktop', () => {
  beforeEach(() => {
    setViewport('desktop')
    currentDetail = makeDetail()
    Object.values(api).forEach((fn) => fn.mockReset())
    api.apiFetch.mockImplementation(async (url: string) =>
      url === '/api/requests/77/' ? jsonResponse(currentDetail) : jsonResponse({}),
    )
    api.getRequestFormOptions.mockResolvedValue({ is_tenant_admin: false })
  })

  afterEach(() => {
    resetViewport()
  })

  it('keeps the bordered table and the desktop actions', async () => {
    const { container } = renderPage()

    await waitFor(() => expect(container.querySelector('.ant-descriptions-bordered')).not.toBeNull())
    expect(screen.queryByTestId('request-detail-mobile')).toBeNull()
    expect(screen.queryByTestId('request-decision-bar')).toBeNull()
    expect(screen.getByText('На рассмотрении')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Добавить заметку' })).toBeInTheDocument()
  })
})
