import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { ChangePasswordModal } from './ChangePasswordModal'

const changePasswordMock = vi.fn()
const successMock = vi.fn()

vi.mock('../../lib/api', () => ({
  changePassword: (...args: unknown[]) => changePasswordMock(...args),
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

describe('ChangePasswordModal', () => {
  beforeEach(() => {
    changePasswordMock.mockReset()
    successMock.mockReset()
  })

  it('submits with trimmed current password', async () => {
    const onClose = vi.fn()
    changePasswordMock.mockResolvedValueOnce({ detail: 'ok' })
    render(<ChangePasswordModal open onClose={onClose} />)

    const inputs = Array.from(document.querySelectorAll('input'))
    fireEvent.change(inputs[0], { target: { value: ' old-pass ' } })
    fireEvent.change(inputs[1], { target: { value: 'new-pass' } })
    fireEvent.change(inputs[2], { target: { value: 'new-pass' } })
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }))

    await waitFor(() => {
      expect(changePasswordMock).toHaveBeenCalledWith({ old_password: 'old-pass', new_password: 'new-pass' })
    })
    expect(successMock).toHaveBeenCalled()
    expect(onClose).toHaveBeenCalled()
  })

  it('shows backend error', async () => {
    changePasswordMock.mockRejectedValueOnce(new Error('Старый пароль неверный'))
    render(<ChangePasswordModal open onClose={() => undefined} />)
    const inputs = Array.from(document.querySelectorAll('input'))
    fireEvent.change(inputs[1], { target: { value: 'new-pass' } })
    fireEvent.change(inputs[2], { target: { value: 'new-pass' } })
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Старый пароль неверный')
  })
})
