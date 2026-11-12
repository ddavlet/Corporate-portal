import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { InvestmentRecordDetailModal } from './InvestmentRecordDetailModal'

const getProjectInvestmentApprovalsMock = vi.fn()
const getInvestReturnApprovalsMock = vi.fn()
const resendProjectMock = vi.fn()
const resendReturnMock = vi.fn()

vi.mock('../../lib/api', () => ({
  getProjectInvestmentApprovals: (...args: unknown[]) => getProjectInvestmentApprovalsMock(...args),
  getInvestReturnApprovals: (...args: unknown[]) => getInvestReturnApprovalsMock(...args),
  resendProjectInvestmentApprovalCard: (...args: unknown[]) => resendProjectMock(...args),
  resendInvestReturnApprovalCard: (...args: unknown[]) => resendReturnMock(...args),
}))

const projectRecord = {
  id: 77,
  date: '2026-04-15',
  amount: '1000',
  currency: 'USD',
  comment: '',
  confirmed: false,
  created_at: '2026-04-15T10:00:00Z',
}

function approval(over: Record<string, unknown> = {}) {
  return {
    id: 501,
    step: 1,
    step_type: 'serial',
    decision: 'pending',
    approver_username: 'Директор',
    resend_count: 0,
    can_resend: true,
    resend_available_at: null,
    ...over,
  }
}

function renderModal(kind: 'project' | 'return' = 'project') {
  return render(
    <MemoryRouter>
      <InvestmentRecordDetailModal
        open
        onCancel={() => {}}
        kind={kind}
        record={projectRecord as never}
      />
    </MemoryRouter>,
  )
}

describe('InvestmentRecordDetailModal — переотправка карточки', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('показывает кнопку у ожидающего этапа и переотправляет карточку вложения', async () => {
    getProjectInvestmentApprovalsMock.mockResolvedValue([approval()])
    resendProjectMock.mockResolvedValue(undefined)

    renderModal('project')

    const button = await screen.findByRole('button', { name: /Переотправить \(3 из 3\)/ })
    fireEvent.click(button)

    await waitFor(() => expect(resendProjectMock).toHaveBeenCalledWith(501))
    expect(resendReturnMock).not.toHaveBeenCalled()
    await waitFor(() => expect(getProjectInvestmentApprovalsMock).toHaveBeenCalledTimes(2))
  })

  it('для выплаты использует эндпоинт согласований выплат', async () => {
    getInvestReturnApprovalsMock.mockResolvedValue([approval({ id: 601 })])
    resendReturnMock.mockResolvedValue(undefined)

    renderModal('return')

    fireEvent.click(await screen.findByRole('button', { name: /Переотправить/ }))

    await waitFor(() => expect(resendReturnMock).toHaveBeenCalledWith(601))
  })

  it('не показывает кнопку, когда переотправка недоступна', async () => {
    getProjectInvestmentApprovalsMock.mockResolvedValue([approval({ can_resend: false, resend_count: 3 })])

    renderModal('project')

    await screen.findByText('Директор')
    expect(screen.queryByRole('button', { name: /Переотправить/ })).not.toBeInTheDocument()
  })
})

describe('InvestmentRecordDetailModal — без переотправки (телефон портала)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('с allowResend={false} не показывает «Переотправить» у ожидающего этапа', async () => {
    getInvestReturnApprovalsMock.mockResolvedValue([approval({ can_resend: true })])
    render(
      <MemoryRouter>
        <InvestmentRecordDetailModal
          open
          onCancel={() => {}}
          kind="return"
          record={projectRecord as never}
          variant="portal"
          allowResend={false}
        />
      </MemoryRouter>,
    )

    await screen.findByText('Директор')
    expect(screen.getByText('В ожидании (1)')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Переотправить/ })).not.toBeInTheDocument()
    expect(resendReturnMock).not.toHaveBeenCalled()
  })
})

describe('InvestmentRecordDetailModal — расположение подписей', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    getProjectInvestmentApprovalsMock.mockResolvedValue([])
  })

  /** Строка таблицы с подписью «ID»: в горизонтальном виде в ней и значение, в вертикальном — только подпись. */
  function idLabelRow(): HTMLTableRowElement {
    const label = [...document.querySelectorAll('.ant-descriptions-item-label')].find((el) => el.textContent === 'ID')
    return label!.closest('tr') as HTMLTableRowElement
  }

  it('по умолчанию в портале держит подпись и значение в одной строке', async () => {
    renderModal('project')
    await screen.findByText('Заявка на вложение #77')
    expect(idLabelRow().querySelector('.ant-descriptions-item-content')).not.toBeNull()
  })

  it('с descriptionsLayout="vertical" ставит подписи над значениями', async () => {
    render(
      <MemoryRouter>
        <InvestmentRecordDetailModal
          open
          onCancel={() => {}}
          kind="project"
          record={projectRecord as never}
          variant="portal"
          descriptionsLayout="vertical"
        />
      </MemoryRouter>,
    )
    await screen.findByText('Заявка на вложение #77')
    expect(idLabelRow().querySelector('.ant-descriptions-item-content')).toBeNull()
    expect(screen.getByText('77')).toBeInTheDocument()
  })
})
