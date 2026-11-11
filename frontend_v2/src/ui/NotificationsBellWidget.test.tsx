import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { NotificationsBellWidget } from './NotificationsBellWidget'

describe('NotificationsBellWidget', () => {
  it('is a 44×44 touch target in the phone header', () => {
    render(<NotificationsBellWidget count={3} onClick={vi.fn()} size="touch" />)
    const bell = screen.getByRole('button', { name: 'Уведомления: требуется действие (3)' })
    expect(bell).toHaveStyle({ width: '44px', height: '44px' })
    expect(screen.getByTestId('notifications-bell-badge')).toBeInTheDocument()
    expect(screen.getByTitle('3')).toBeInTheDocument()
  })

  it('keeps its size, label and test id by default', () => {
    const onClick = vi.fn()
    render(<NotificationsBellWidget count={0} onClick={onClick} />)
    const bell = screen.getByRole('button', { name: 'Уведомления' })
    expect(bell.style.width).toBe('')
    expect(bell.style.height).toBe('')
    expect(bell).toHaveAttribute('title', 'Уведомления')
    expect(screen.getByTestId('notifications-bell-badge')).toBeInTheDocument()
    fireEvent.click(bell)
    expect(onClick).toHaveBeenCalledTimes(1)
  })
})
