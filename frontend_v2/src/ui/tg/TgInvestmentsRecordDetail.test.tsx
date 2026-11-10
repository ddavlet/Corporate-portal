import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { TgInvestmentsProjectsPage } from './TgInvestmentsProjectsPage'
import { TgInvestmentsReturnsPage } from './TgInvestmentsReturnsPage'

const getFormConfigMock = vi.fn()
const getCompaniesMock = vi.fn()
const getProjectInvestmentsMock = vi.fn()
const getInvestReturnsMock = vi.fn()
const getFundingConfigMock = vi.fn()
const getProjectApprovalsMock = vi.fn()
const getReturnApprovalsMock = vi.fn()

vi.mock('../../lib/api', () => ({
  DEFAULT_INVESTMENT_FORM_CONFIG: { uses_companies: false },
  getInvestmentFormConfig: (...a: unknown[]) => getFormConfigMock(...a),
  getInvestCompanies: (...a: unknown[]) => getCompaniesMock(...a),
  getProjectInvestments: (...a: unknown[]) => getProjectInvestmentsMock(...a),
  getInvestReturns: (...a: unknown[]) => getInvestReturnsMock(...a),
  getInvestmentFundingConfig: (...a: unknown[]) => getFundingConfigMock(...a),
  getProjectInvestmentApprovals: (...a: unknown[]) => getProjectApprovalsMock(...a),
  getInvestReturnApprovals: (...a: unknown[]) => getReturnApprovalsMock(...a),
  resendProjectInvestmentApprovalCard: vi.fn(),
  resendInvestReturnApprovalCard: vi.fn(),
}))

vi.mock('../admin/AdminEditRecordButton', () => ({
  AdminEditRecordButton: () => null,
}))

const PROJECT = {
  id: 42,
  company: null,
  date: '2026-11-05',
  amount: '5000000',
  currency: 'UZS',
  comment: 'Вложение в ремонт',
  confirmed: false,
  created_at: '2026-11-05T10:00:00Z',
  funding_method: 'cash',
  source_requests: [{ id: 9001, amount: '5000000', currency: 'UZS', payment_type: 'Инвест. наличные' }],
}

const RETURN = {
  id: 77,
  company: null,
  date: '2026-11-06',
  billing_date: '2026-10-01',
  sum: '1200',
  currency: 'USD',
  type: 'дивиденды',
  recipient: 'инвестор',
  comment: '',
  confirmed: true,
  created_at: '2026-11-06T10:00:00Z',
}

function renderPage(node: ReactNode) {
  return render(<MemoryRouter>{node}</MemoryRouter>)
}

describe('Мини-приложение: карточки инвестиций открывают детали', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    getFormConfigMock.mockResolvedValue({ uses_companies: false })
    getCompaniesMock.mockResolvedValue([])
    getFundingConfigMock.mockResolvedValue({ is_enabled: false })
    getProjectInvestmentsMock.mockResolvedValue([PROJECT])
    getInvestReturnsMock.mockResolvedValue([RETURN])
    getProjectApprovalsMock.mockResolvedValue([])
    getReturnApprovalsMock.mockResolvedValue([])
  })

  it('нажатие на заявку на вложение открывает её детали со ссылкой на заявку внутри мини-приложения', async () => {
    renderPage(<TgInvestmentsProjectsPage />)

    const card = await screen.findByRole('button', { name: /Вложение в ремонт/ })
    fireEvent.click(card)

    expect(await screen.findByText('Заявка на вложение #42')).toBeInTheDocument()
    await waitFor(() => expect(getProjectApprovalsMock).toHaveBeenCalledWith(42))
    const link = screen.getByRole('link', { name: /№9001/ })
    expect(link).toHaveAttribute('href', '/tg/requests/9001')
    // Мини-приложение: подписи над значениями, чтобы на узком экране не сжимать значения
    expect(document.querySelector('.ant-descriptions-item-label')?.closest('tr')?.querySelector('.ant-descriptions-item-content')).toBeNull()
  })

  it('нажатие на выплату открывает её детали', async () => {
    renderPage(<TgInvestmentsReturnsPage />)

    const card = await screen.findByRole('button', { name: /Дивиденды/ })
    fireEvent.click(card)

    expect(await screen.findByText('Выплата #77')).toBeInTheDocument()
    await waitFor(() => expect(getReturnApprovalsMock).toHaveBeenCalledWith(77))
  })
})
