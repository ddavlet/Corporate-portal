import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { TgCommentPage } from './TgCommentPage'

const listRequestCommentsMock = vi.fn()
const createRequestCommentMock = vi.fn()
const successMock = vi.fn()
const closeMock = vi.fn()

vi.mock('../../lib/api', () => ({
  listRequestComments: (...args: unknown[]) => listRequestCommentsMock(...args),
  createRequestComment: (...args: unknown[]) => createRequestCommentMock(...args),
}))

vi.mock('antd', async () => {
  const mod = await vi.importActual<typeof import('antd')>('antd')
  return {
    ...mod,
    message: {
      ...mod.message,
      success: (...args: unknown[]) => successMock(...args),
    },
  }
})

function renderPage(url: string) {
  window.history.pushState({}, '', url)
  return render(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route path="/tg/comment" element={<TgCommentPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('TgCommentPage', () => {
  beforeEach(() => {
    listRequestCommentsMock.mockReset()
    createRequestCommentMock.mockReset()
    successMock.mockReset()
    closeMock.mockReset()
    ;(window as Window).Telegram = {
      WebApp: {
        initData: '',
        initDataUnsafe: {},
        ready: vi.fn(),
        close: closeMock,
      },
    }
  })

  it('loads and renders existing comments for the request', async () => {
    listRequestCommentsMock.mockResolvedValue([
      { id: 1, body: 'Первый комментарий', created_at: '2026-05-29T10:00:00Z', created_by: 7, created_by_full_name: 'Иван Иванов' },
    ])
    renderPage('/tg/comment?request_id=42')

    await waitFor(() => {
      expect(listRequestCommentsMock).toHaveBeenCalledWith(42)
    })
    expect(await screen.findByText('Первый комментарий')).toBeInTheDocument()
    expect(screen.getByText('Иван Иванов')).toBeInTheDocument()
  })

  it('submits a new comment and refreshes the list without closing the app', async () => {
    listRequestCommentsMock.mockResolvedValue([])
    createRequestCommentMock.mockResolvedValueOnce({
      id: 2,
      body: 'Новый',
      created_at: '2026-05-29T11:00:00Z',
      created_by: 7,
      created_by_full_name: 'Иван Иванов',
    })
    renderPage('/tg/comment?request_id=42')

    await waitFor(() => {
      expect(listRequestCommentsMock).toHaveBeenCalledTimes(1)
    })

    fireEvent.change(screen.getByPlaceholderText('Напишите комментарий...'), { target: { value: 'Новый' } })
    fireEvent.click(screen.getByRole('button', { name: 'Отправить комментарий' }))

    await waitFor(() => {
      expect(createRequestCommentMock).toHaveBeenCalledWith(42, 'Новый')
    })
    expect(successMock).toHaveBeenCalled()
    await waitFor(() => {
      expect(listRequestCommentsMock).toHaveBeenCalledTimes(2)
    })
    expect(closeMock).not.toHaveBeenCalled()
  })

  it('shows error when request id is missing', async () => {
    renderPage('/tg/comment')
    expect(await screen.findByText(/Идентификатор заявки не определён/)).toBeInTheDocument()
    expect(listRequestCommentsMock).not.toHaveBeenCalled()
  })
})
