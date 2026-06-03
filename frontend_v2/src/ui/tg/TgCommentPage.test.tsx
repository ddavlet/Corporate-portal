import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { TgCommentPage } from './TgCommentPage'

const createRequestCommentMock = vi.fn()
const successMock = vi.fn()
const closeMock = vi.fn()

vi.mock('../../lib/api', () => ({
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
    vi.useFakeTimers()
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

  afterEach(() => {
    vi.useRealTimers()
  })

  it('shows request id and comment form when request_id is valid', async () => {
    renderPage('/tg/comment?request_id=42')

    await waitFor(() => {
      expect(screen.getByText(/Заявка #42/)).toBeInTheDocument()
    })
    expect(screen.getByPlaceholderText('Напишите комментарий...')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Отправить комментарий' })).toBeDisabled()
  })

  it('submits a comment and closes the WebApp after success', async () => {
    createRequestCommentMock.mockResolvedValueOnce({
      id: 2,
      body: 'Новый',
      created_at: '2026-05-29T11:00:00Z',
      created_by: 7,
      created_by_full_name: 'Иван Иванов',
    })
    renderPage('/tg/comment?request_id=42')

    await waitFor(() => {
      expect(screen.getByText(/Заявка #42/)).toBeInTheDocument()
    })

    fireEvent.change(screen.getByPlaceholderText('Напишите комментарий...'), { target: { value: 'Новый' } })
    fireEvent.click(screen.getByRole('button', { name: 'Отправить комментарий' }))

    await waitFor(() => {
      expect(createRequestCommentMock).toHaveBeenCalledWith(42, 'Новый')
    })
    expect(successMock).toHaveBeenCalled()
    expect(await screen.findByText('Комментарий сохранён')).toBeInTheDocument()

    act(() => {
      vi.advanceTimersByTime(800)
    })
    expect(closeMock).toHaveBeenCalled()
  })

  it('shows warning when request id is missing', async () => {
    renderPage('/tg/comment')
    expect(await screen.findByText(/Идентификатор заявки не определён/)).toBeInTheDocument()
    expect(createRequestCommentMock).not.toHaveBeenCalled()
  })
})
