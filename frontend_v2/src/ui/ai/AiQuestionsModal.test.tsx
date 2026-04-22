import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AiQuestionsModal } from './AiQuestionsModal'

const askAiQuestionMock = vi.fn()

vi.mock('../../lib/api', () => ({
  askAiQuestion: (...args: unknown[]) => askAiQuestionMock(...args),
}))

describe('AiQuestionsModal', () => {
  beforeEach(() => {
    askAiQuestionMock.mockReset()
  })

  it('submits question and renders ai response', async () => {
    askAiQuestionMock.mockResolvedValueOnce({ session_id: 's1', response: 'answer' })
    render(<AiQuestionsModal open onClose={() => undefined} />)

    fireEvent.change(screen.getByPlaceholderText('Введите вопрос...'), { target: { value: 'Что по отчёту?' } })
    fireEvent.click(screen.getByRole('button', { name: 'Отправить' }))

    await waitFor(() => {
      expect(askAiQuestionMock).toHaveBeenCalledWith({ question: 'Что по отчёту?', session_id: undefined })
    })
    expect(await screen.findByText('answer')).toBeInTheDocument()
  })

  it('shows error when request fails', async () => {
    askAiQuestionMock.mockRejectedValueOnce(new Error('service unavailable'))
    render(<AiQuestionsModal open onClose={() => undefined} />)
    fireEvent.change(screen.getByPlaceholderText('Введите вопрос...'), { target: { value: 'test' } })
    fireEvent.click(screen.getByRole('button', { name: 'Отправить' }))
    expect(await screen.findByText('service unavailable')).toBeInTheDocument()
  })
})
