import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { RequestAiChatButton } from './RequestAiChatButton'

const openRequestAiChatMock = vi.fn()

vi.mock('./requestAiChat', () => ({
  openRequestAiChat: () => openRequestAiChatMock(),
}))

describe('RequestAiChatButton', () => {
  it('opens n8n chat on click', () => {
    render(<RequestAiChatButton />)
    fireEvent.click(screen.getByRole('button', { name: /Заявка с ИИ \(Бета\)/ }))
    expect(openRequestAiChatMock).toHaveBeenCalledTimes(1)
  })
})
