import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const getReportRulesMock = vi.fn()
const updateReportRulesMock = vi.fn()
vi.mock('../../../lib/reportsApi', () => ({
  getReportRules: (...args: unknown[]) => getReportRulesMock(...args),
  updateReportRules: (...args: unknown[]) => updateReportRulesMock(...args),
}))

const getPoolMock = vi.fn()
vi.mock('../../../lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../lib/api')>()
  return { ...actual, getTenantPnlPaymentPurposePool: (...args: unknown[]) => getPoolMock(...args) }
})

const notifyApiSuccessMock = vi.fn()
vi.mock('../../../lib/apiNotify', () => ({
  notifyApiSuccess: (...args: unknown[]) => notifyApiSuccessMock(...args),
  notifyApiError: vi.fn(),
  notifyNetworkError: vi.fn(),
  setAntdMessageApi: vi.fn(),
}))

import { ApiError } from '../../../lib/api'
import { ReportRulesForm } from './ReportRulesForm'

const RULES = {
  start_month: '2026-02',
  opening_balance: '0',
  cash_exclude_operations: [],
  request_exclude_categories: [],
  request_payment_types_for_pnl: ['Перечисление'],
  payment_purpose_operational: ['Аренда'],
  payment_purpose_other: ['Налоги'],
  payment_purpose_invest_returns: [],
  invest_return_type_operational: ['проценты', 'доля_прибыли'],
  invest_return_type_other: ['тело_инвестиций'],
  invest_return_type_invest_returns: ['дивиденды'],
}

function rulesOf(report: 'pnl' | 'cashflow', overrides: Record<string, unknown> = {}) {
  return {
    report,
    source: 'backend',
    rules: RULES,
    updated_at: '2026-09-30T10:00:00+05:00',
    diagnostics: { unassigned_payment_purposes: [] },
    ...overrides,
  }
}

describe('ReportRulesForm', () => {
  beforeEach(() => {
    getReportRulesMock.mockReset()
    updateReportRulesMock.mockReset()
    getPoolMock.mockReset().mockResolvedValue({ purposes: ['Аренда', 'Налоги'] })
  })

  it('loads the rules of its own report, then their diagnostics when the app calculates the report', async () => {
    getReportRulesMock.mockResolvedValue(rulesOf('cashflow'))
    render(<ReportRulesForm report="cashflow" />)
    expect(await screen.findByDisplayValue('2026-02')).toBeInTheDocument()
    expect(getReportRulesMock.mock.calls).toEqual([['cashflow'], ['cashflow', { diagnostics: true }]])
    expect(getPoolMock).toHaveBeenCalledWith({ forPnlPaymentTypes: ['Перечисление'] })
  })

  it('does not check the rules of a report that n8n builds', async () => {
    getReportRulesMock.mockResolvedValue(
      rulesOf('cashflow', {
        source: 'n8n',
        diagnostics: { unassigned_payment_purposes: [{ purpose: 'Связь', count: 2, amount: '10.00' }] },
      }),
    )
    render(<ReportRulesForm report="cashflow" />)
    expect(await screen.findByDisplayValue('2026-02')).toBeInTheDocument()
    expect(getReportRulesMock.mock.calls).toEqual([['cashflow']])
    expect(screen.queryByText('Связь (2)')).toBeNull()
  })

  it('asks for bank exclusions only in the PnL rules', async () => {
    getReportRulesMock.mockResolvedValue(rulesOf('cashflow'))
    const { unmount } = render(<ReportRulesForm report="cashflow" />)
    await screen.findByDisplayValue('2026-02')
    expect(screen.queryByLabelText('Исключить банковские поступления')).toBeNull()
    unmount()
    getReportRulesMock.mockResolvedValue(rulesOf('pnl'))
    render(<ReportRulesForm report="pnl" />)
    expect(await screen.findByLabelText('Исключить банковские поступления')).toBeInTheDocument()
  })

  it('saves the full rules of its report and tells the page', async () => {
    getReportRulesMock.mockResolvedValue(rulesOf('cashflow'))
    updateReportRulesMock.mockResolvedValue(rulesOf('cashflow'))
    const onSaved = vi.fn()
    render(<ReportRulesForm report="cashflow" onSaved={onSaved} />)
    fireEvent.change(await screen.findByLabelText('Начальный остаток'), { target: { value: '500' } })
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }))
    await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1))
    const [report, payload] = updateReportRulesMock.mock.calls[0]
    expect(report).toBe('cashflow')
    expect(payload.source).toBe('backend')
    expect(payload.rules).toMatchObject({ start_month: '2026-02', opening_balance: '500', payment_purpose_operational: ['Аренда'] })
    expect(payload.rules).not.toHaveProperty('bank_exclude_purposes')
    expect(notifyApiSuccessMock).toHaveBeenCalledWith('Правила сохранены')
  })

  it('keeps what was typed when saving fails', async () => {
    getReportRulesMock.mockResolvedValue(rulesOf('pnl'))
    updateReportRulesMock.mockRejectedValue(new ApiError(400, "rules missing keys: ['start_month']"))
    const onSaved = vi.fn()
    render(<ReportRulesForm report="pnl" onSaved={onSaved} />)
    fireEvent.change(await screen.findByLabelText('Стартовый месяц периода'), { target: { value: '2025-01' } })
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }))
    expect(await screen.findByText("rules missing keys: ['start_month']")).toBeInTheDocument()
    expect(screen.getByDisplayValue('2025-01')).toBeInTheDocument()
    expect(onSaved).not.toHaveBeenCalled()
  })

  it('offers to try again when the rules cannot be loaded', async () => {
    getReportRulesMock.mockRejectedValueOnce(new ApiError(502, 'Сервер недоступен')).mockResolvedValue(rulesOf('pnl'))
    render(<ReportRulesForm report="pnl" />)
    expect(await screen.findByText('Сервер недоступен')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Повторить' }))
    expect(await screen.findByDisplayValue('2026-02')).toBeInTheDocument()
  })

  it('points at paid payment purposes that no section takes', async () => {
    getReportRulesMock.mockResolvedValue(
      rulesOf('pnl', { diagnostics: { unassigned_payment_purposes: [{ purpose: 'Связь', count: 2, amount: '10.00' }] } }),
    )
    render(<ReportRulesForm report="pnl" />)
    expect(await screen.findByText('Связь (2)')).toBeInTheDocument()
  })
})
