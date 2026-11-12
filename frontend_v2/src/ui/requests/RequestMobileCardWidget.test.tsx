import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { theme } from 'antd'
import { describe, expect, it } from 'vitest'
import { contrastRatio } from '../../test/contrast'
import { mobileToneTextColor } from './mobileActionsTheme'
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
    ['APPROVED', 'Согласована', 'success', mobileToneTextColor('success', token), token.colorSuccessBg],
    ['3', 'На согласовании · шаг 3', 'processing', mobileToneTextColor('info', token), token.colorInfoBg],
    ['REJECTED', 'Отклонена', 'error', mobileToneTextColor('error', token), token.colorErrorBg],
  ])('writes %s in a dark shade on the light fill, at 4.5:1 or more', (status, label, tone, color, backgroundColor) => {
    render(<RequestStatusTag status={status} />)
    const tag = screen.getByText(label)
    expect(tag).toHaveAttribute('data-tone', tone)
    expect(tag).toHaveStyle({ color, backgroundColor })
    expect(contrastRatio(tag.style.color, tag.style.backgroundColor)).toBeGreaterThanOrEqual(4.5)
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
    expect(note).toHaveStyle({ color: mobileToneTextColor('error', token) })
    expect(note).not.toHaveStyle({ color: token.colorError })
    // The card's red tint (styles.css .m-card--payed-no-expense).
    expect(contrastRatio(note.style.color, 'rgba(255, 77, 79, 0.09)')).toBeGreaterThanOrEqual(4.5)
  })
})
