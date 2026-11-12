import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { theme } from 'antd'
import { describe, expect, it } from 'vitest'
import { RequestMobileCardWidget, RequestStatusTag, type RequestFeedRow } from './RequestMobileCardWidget'

const token = theme.getDesignToken()

function row(overrides: Partial<RequestFeedRow> = {}): RequestFeedRow {
  return {
    id: 7,
    title: 'Аренда офиса',
    amount: 2500000,
    currency: 'UZS',
    status: 'APPROVED',
    payment_type: 'Перечисление',
    vendor: 'ООО Альфа',
    requester: 3,
    requester_username: 'ivanov',
    submitted_at: '2026-11-05T10:00:00Z',
    expense_link: { module: 'bank', id: 5 },
    ...overrides,
  }
}

function renderCard(request: RequestFeedRow) {
  return render(
    <MemoryRouter>
      <RequestMobileCardWidget request={request} />
    </MemoryRouter>,
  )
}

describe('RequestStatusTag — contrast', () => {
  it.each([
    ['APPROVED', 'Согласована', 'success', token.colorSuccessTextHover, token.colorSuccessBg],
    ['3', 'На согласовании · шаг 3', 'processing', token.colorInfoTextHover, token.colorInfoBg],
    ['REJECTED', 'Отклонена', 'error', token.colorErrorTextHover, token.colorErrorBg],
  ])('writes %s at shade 8 on the light fill', (status, label, tone, color, backgroundColor) => {
    render(<RequestStatusTag status={status} />)
    const tag = screen.getByText(label)
    expect(tag).toHaveAttribute('data-tone', tone)
    expect(tag).toHaveStyle({ color, backgroundColor })
  })

  it('keeps the regular text colour for a neutral status', () => {
    render(<RequestStatusTag status="PAYED" />)
    const tag = screen.getByText('Оплачена')
    expect(tag).toHaveAttribute('data-tone', 'default')
    expect(tag).toHaveStyle({ color: token.colorText })
  })
})

describe('RequestMobileCardWidget — contrast', () => {
  it('writes the meta line in the secondary text colour, not the tertiary one', () => {
    renderCard(row())
    const meta = within(screen.getByTestId('request-card-7')).getByText(/Перечисление · ivanov/)
    expect(meta).toHaveStyle({ color: token.colorTextSecondary })
    expect(meta).not.toHaveStyle({ color: token.colorTextTertiary })
  })

  it('writes «Оплачена, но расход не найден» in dark red on the red tint', () => {
    renderCard(row({ status: 'PAYED', expense_link: null }))
    const note = screen.getByTestId('payed-no-expense-note')
    expect(note).toHaveTextContent('Оплачена, но расход не найден')
    expect(note).toHaveStyle({ color: token.colorErrorTextHover })
    expect(note).not.toHaveStyle({ color: token.colorError })
  })
})
