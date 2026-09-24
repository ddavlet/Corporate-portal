import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { PayrollDocumentFormModal } from './PayrollDocumentFormModal'

const listEmployeesMock = vi.fn()
const createPayrollDraftMock = vi.fn()

vi.mock('../../lib/api', async () => {
  const actual = await vi.importActual<typeof import('../../lib/api')>('../../lib/api')
  return {
    ...actual,
    listEmployees: (...a: unknown[]) => listEmployeesMock(...a),
    createEmployee: vi.fn(),
    createPayrollDraft: (...a: unknown[]) => createPayrollDraftMock(...a),
    updatePayrollDraft: vi.fn(),
  }
})

describe('PayrollDocumentFormModal', () => {
  beforeEach(() => {
    listEmployeesMock.mockResolvedValue([
      { id: 1, full_name: 'Alice' },
      { id: 2, full_name: 'Bob' },
    ])
    createPayrollDraftMock.mockReset()
  })

  it('does not offer an employee already chosen in another row', async () => {
    render(
      <PayrollDocumentFormModal
        open
        onClose={() => {}}
        onSaved={() => {}}
        initial={{
          id: 5, doc_id: null, label: '№5', created_at: '', total_sum: '10', status: 'draft', source: 'portal',
          payout_mode: 'legacy', period_month: '2026-09-01', kind: 'salary', closed_underpaid_at: null,
          close_comment: '', current_request: null, paid_total: '0', remaining_total: '10',
          lines: [
            { id: 1, line_no: 1, employee: 'Alice', employee_id: 1, item: 'Зарплата', sum: '10', days_plan: null,
              days_fact: null, period_start: null, period_end: null, approval: true },
          ],
        }}
      />,
    )
    fireEvent.click(await screen.findByRole('button', { name: /Добавить сотрудника в список/ }))
    const selects = await screen.findAllByRole('combobox')
    fireEvent.mouseDown(selects[selects.length - 1])

    // The brief's original assertion (`screen.queryAllByTitle('Alice').filter((el) =>
    // el.closest('.ant-select-item-option'))`) leans on antd giving each dropdown
    // option a `title` attribute equal to its label. That's true for antd 5's default
    // Select rendering, but it's an implementation detail of the tooltip/ellipsis
    // handling rather than a documented contract. Reading the dropdown options
    // directly by their well-known class (`.ant-select-item-option`) and comparing
    // rendered text is a more direct/robust way to assert "which options are offered"
    // without depending on the title attribute existing or matching exactly.
    await waitFor(() => {
      const optionTexts = Array.from(document.querySelectorAll('.ant-select-item-option')).map((el) =>
        el.textContent?.trim(),
      )
      expect(optionTexts).toContain('Bob')
      expect(optionTexts).not.toContain('Alice')
    })
  })
})
