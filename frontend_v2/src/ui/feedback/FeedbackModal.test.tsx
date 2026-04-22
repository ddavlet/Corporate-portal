import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { FeedbackModal } from './FeedbackModal'

const refineFeedbackWithAiMock = vi.fn()
const submitFeedbackMock = vi.fn()
const successMock = vi.fn()
const warningMock = vi.fn()

vi.mock('../../lib/api', () => ({
  refineFeedbackWithAi: (...args: unknown[]) => refineFeedbackWithAiMock(...args),
  submitFeedback: (...args: unknown[]) => submitFeedbackMock(...args),
}))

vi.mock('antd', async () => {
  const mod = await vi.importActual<typeof import('antd')>('antd')
  return {
    ...mod,
    message: {
      ...mod.message,
      success: (...args: unknown[]) => successMock(...args),
      warning: (...args: unknown[]) => warningMock(...args),
    },
  }
})

describe('FeedbackModal', () => {
  beforeEach(() => {
    refineFeedbackWithAiMock.mockReset()
    submitFeedbackMock.mockReset()
    successMock.mockReset()
    warningMock.mockReset()
  })

  it('refines and submits feedback', async () => {
    const onClose = vi.fn()
    refineFeedbackWithAiMock.mockResolvedValueOnce({ feedback: 'structured feedback' })
    submitFeedbackMock.mockResolvedValueOnce({ id: 1, delivery: { status: 'sent', error: null } })
    render(<FeedbackModal open onClose={onClose} pagePath="/requests" />)

    fireEvent.click(screen.getByTitle('Улучшение'))
    fireEvent.click(screen.getByTitle('Ошибка'))
    fireEvent.change(screen.getByPlaceholderText('Текст комментария…'), { target: { value: 'raw feedback' } })
    fireEvent.click(screen.getByRole('button', { name: 'Сформировать' }))

    await waitFor(() => {
      expect(refineFeedbackWithAiMock).toHaveBeenCalledWith({ kind: 'error', text: 'raw feedback' })
    })

    await waitFor(() => {
      expect(screen.getByPlaceholderText('Текст комментария…')).toHaveValue('structured feedback')
    })

    fireEvent.click(screen.getByRole('button', { name: 'Отправить' }))
    await waitFor(() => {
      expect(submitFeedbackMock).toHaveBeenCalledWith({ kind: 'error', body: 'structured feedback', page_path: '/requests' })
    })
    expect(successMock).toHaveBeenCalled()
    expect(onClose).toHaveBeenCalled()
  })

  it('renders refine error', async () => {
    refineFeedbackWithAiMock.mockRejectedValueOnce(new Error('n8n offline'))
    render(<FeedbackModal open onClose={() => undefined} pagePath="/requests" />)
    fireEvent.click(screen.getByTitle('Улучшение'))
    fireEvent.click(screen.getByTitle('Ошибка'))
    fireEvent.change(screen.getByPlaceholderText('Текст комментария…'), { target: { value: 'raw feedback' } })
    fireEvent.click(screen.getByRole('button', { name: 'Сформировать' }))
    expect(await screen.findByText(/n8n offline/i)).toBeInTheDocument()
  })
})
