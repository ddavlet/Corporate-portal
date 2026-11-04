import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { Modal } from 'antd'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const getMock = vi.fn()
const saveMock = vi.fn()
const previewMock = vi.fn()
const sendTestMock = vi.fn()
const sendNowMock = vi.fn()
const dispatchesMock = vi.fn()

vi.mock('../../lib/api', () => {
  class InvestReportUnavailableError extends Error {}
  return {
    InvestReportUnavailableError,
    getInvestReportConfig: () => getMock(),
    saveInvestReportConfig: (...args: unknown[]) => saveMock(...args),
    previewInvestReport: (...args: unknown[]) => previewMock(...args),
    sendInvestReportTest: (...args: unknown[]) => sendTestMock(...args),
    sendInvestReportNow: () => sendNowMock(),
    listInvestReportDispatches: (...args: unknown[]) => dispatchesMock(...args),
  }
})

import { InvestReportUnavailableError } from '../../lib/api'
import { InvestmentReportConfigPage, renderReportHtml } from './InvestmentReportConfigPage'

const config = {
  is_active: true,
  telegram_chat_id: 7,
  weekday: 0,
  send_hour: 10,
  target_annual_rate: '34.72',
  start_month: null,
  last_payouts_count: 3,
  late_payment_day: 25,
  updated_at: '2026-10-26T10:00:00+05:00',
  options: { chats: [{ id: 7, name: 'Инвесторы Aqua' }] },
}

const { options: _options, updated_at: _updatedAt, ...configDto } = config

const dispatch = {
  id: 1,
  report_date: '2026-10-26',
  kind: 'manual',
  status: 'sent',
  chat_id: '-1001',
  chat_name: 'Инвесторы Aqua',
  error: '',
  created_by_name: 'Админ',
  created_at: '2026-10-26T11:00:00+05:00',
}

function renderPage() {
  return render(
    <MemoryRouter>
      <InvestmentReportConfigPage />
    </MemoryRouter>,
  )
}

describe('renderReportHtml', () => {
  it('keeps only <b> and shows other markup as text', () => {
    const { container } = render(<div>{renderReportHtml('📊 <b>A&amp;B &lt;i&gt;</b> · <i>x</i>')}</div>)
    expect(container.querySelectorAll('b')).toHaveLength(1)
    expect(container.querySelector('b')?.textContent).toBe('A&B <i>')
    expect(container.querySelector('i')).toBeNull()
    expect(container.textContent).toBe('📊 A&B <i> · <i>x</i>')
  })
})

describe('InvestmentReportConfigPage', () => {
  afterEach(() => {
    Modal.destroyAll()
  })

  beforeEach(() => {
    getMock.mockReset().mockResolvedValue(config)
    saveMock.mockReset().mockResolvedValue(config)
    previewMock.mockReset().mockResolvedValue({ text: '📊 <b>Lemonfit AQUA</b> · 26.10.2026', metrics: {} })
    sendTestMock.mockReset().mockResolvedValue({ ...dispatch, kind: 'test' })
    sendNowMock.mockReset().mockResolvedValue(dispatch)
    dispatchesMock.mockReset().mockResolvedValue([dispatch])
  })

  it('fills the form from the API and shows the journal', async () => {
    renderPage()
    expect(await screen.findByText('Инвесторы Aqua', { selector: '.ant-select-selection-item' })).toBeInTheDocument()
    expect(screen.getByRole('switch', { name: 'Включено' })).toBeChecked()
    expect(screen.getByRole('spinbutton', { name: 'Целевая доходность' })).toHaveValue('34,72')
    expect(await screen.findByText('Вручную в группу')).toBeInTheDocument()
  })

  it('saves the loaded config unchanged', async () => {
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: 'Сохранить' }))
    await waitFor(() => expect(saveMock).toHaveBeenCalledTimes(1))
    expect(saveMock).toHaveBeenCalledWith(configDto)
  })

  it('redraws the preview when calculation settings change', async () => {
    renderPage()
    expect(await screen.findByText('Lemonfit AQUA', { selector: 'b' }, { timeout: 2000 })).toBeInTheDocument()
    expect(previewMock).toHaveBeenCalledTimes(1)
    expect(previewMock.mock.calls[0][0]).toMatchObject({ target_annual_rate: '34.72', last_payouts_count: 3 })

    previewMock.mockResolvedValue({ text: '📊 <b>Обновлено</b>', metrics: {} })
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Число последних выплат' }), { target: { value: '5' } })
    expect(await screen.findByText('Обновлено', { selector: 'b' }, { timeout: 2000 })).toBeInTheDocument()
    expect(previewMock).toHaveBeenLastCalledWith(expect.objectContaining({ last_payouts_count: 5 }), expect.anything())
  })

  it('shows a stub instead of the form on 403/404', async () => {
    getMock.mockReset().mockRejectedValue(new InvestReportUnavailableError('nope'))
    renderPage()
    expect(await screen.findByText('Настройка недоступна')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Сохранить' })).toBeNull()
  })

  it('asks for confirmation before sending to the group', async () => {
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /Отправить в группу сейчас/ }))
    const [title] = await screen.findAllByText('Отправить отчёт в группу сейчас?')
    const dialog = title.closest('[role="dialog"]') as HTMLElement
    expect(dialog).not.toBeNull()
    expect(within(dialog).getByText(/«Инвесторы Aqua»/)).toBeInTheDocument()
    expect(sendNowMock).not.toHaveBeenCalled()
    fireEvent.click(within(dialog).getByRole('button', { name: 'Отправить' }))
    await waitFor(() => expect(sendNowMock).toHaveBeenCalledTimes(1))
  })

  it('sends a trial report with the unsaved settings', async () => {
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /Отправить мне/ }))
    await waitFor(() => expect(sendTestMock).toHaveBeenCalledTimes(1))
    expect(sendTestMock.mock.calls[0][0]).toMatchObject({ target_annual_rate: '34.72', late_payment_day: 25 })
  })
})
