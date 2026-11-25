import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  RequestEditModal,
  requestEditDraftFromDetail,
  type RequestEditModalProps,
} from './RequestEditModal'

const listVendorsMock = vi.fn()

vi.mock('../../lib/api', () => ({
  listVendors: (...args: unknown[]) => listVendorsMock(...args),
}))

const detail = {
  title: 'Сушилка для рук',
  description: 'Сушилка электрическая для рук 2 шт',
  amount: 5376000,
  currency: 'UZS',
  status: 'PAYED',
  urgency: 'Обычно',
  payment_type: 'Перечисление',
  category: 'Оборудование',
  vendor: 'SAYINA STROY',
  vendor_ref: 42,
  payment_purpose: '',
  expense_id: '312',
  billing_date: '2026-11-01',
  requester: 7,
  amortization_months: 1,
}

function renderModal(overrides: Partial<RequestEditModalProps> = {}) {
  const onSave = vi.fn()
  const onCancel = vi.fn()
  const props: RequestEditModalProps = {
    open: true,
    requestId: 9326,
    initialDraft: requestEditDraftFromDetail(detail),
    paymentTypeConfigs: [
      { payment_type: 'Перечисление', requester_ids: [], requesters: [], vendor_ids: [], payment_purposes: [] },
    ],
    paymentTypeOptions: [{ value: 'Перечисление', label: 'Перечисление' }],
    categoryOptions: [{ id: 1, name: 'Оборудование' }],
    requesterOptions: [{ value: '7', label: 'Наталья' }],
    saving: false,
    onCancel,
    onSave,
    ...overrides,
  }
  render(<RequestEditModal {...props} />)
  return { onSave, onCancel }
}

describe('RequestEditModal', () => {
  beforeEach(() => {
    listVendorsMock.mockReset().mockResolvedValue([])
  })

  it('keeps «Сохранить» disabled until something changes, then saves the edited draft', async () => {
    const { onSave } = renderModal()

    const save = await screen.findByRole('button', { name: 'Сохранить' })
    expect(save).toBeDisabled()

    fireEvent.change(screen.getByLabelText('Описание'), { target: { value: 'Сушилка 3 шт' } })
    expect(save).toBeEnabled()
    fireEvent.click(save)

    expect(onSave).toHaveBeenCalledTimes(1)
    expect(onSave.mock.calls[0][0]).toMatchObject({ description: 'Сушилка 3 шт', vendorRefId: 42, status: 'PAYED' })
  })

  it('shows the error under the field instead of saving an empty title', async () => {
    const { onSave } = renderModal()

    fireEvent.change(await screen.findByLabelText('Название'), { target: { value: '   ' } })
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }))

    expect(await screen.findByText('Введите название заявки')).toBeInTheDocument()
    expect(onSave).not.toHaveBeenCalled()
  })

  it('closes at once when nothing was changed', async () => {
    const first = renderModal()
    fireEvent.click(await screen.findByRole('button', { name: 'Отмена' }))
    expect(first.onCancel).toHaveBeenCalledTimes(1)
  })

  it('asks before dropping unsaved changes', async () => {
    const { onCancel } = renderModal()
    fireEvent.change(await screen.findByLabelText('Название'), { target: { value: 'Другое название' } })
    fireEvent.click(screen.getByRole('button', { name: 'Отмена' }))

    expect(await screen.findByText('Закрыть без сохранения?')).toBeInTheDocument()
    expect(onCancel).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: 'Закрыть' }))
    await waitFor(() => expect(onCancel).toHaveBeenCalledTimes(1))
  })

  it('shows a vendor stored as text without a directory link and saves it unchanged', async () => {
    const { onSave } = renderModal({
      initialDraft: requestEditDraftFromDetail({ ...detail, vendor: 'ИП Старый', vendor_ref: null }),
    })

    expect(await screen.findByText('ИП Старый')).toBeInTheDocument()
    expect(screen.getByText('Поставщик не привязан к справочнику')).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Описание'), { target: { value: 'Уточнили' } })
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }))
    expect(onSave.mock.calls[0][0]).toMatchObject({ vendor: 'ИП Старый', vendorRefId: null })
  })

  it('drops the vendor when the payment type switches to another vendor directory', async () => {
    const { onSave } = renderModal({
      paymentTypeOptions: [
        { value: 'Перечисление', label: 'Перечисление' },
        { value: 'Наличные', label: 'Наличные' },
      ],
    })

    fireEvent.mouseDown(await screen.findByLabelText('Тип оплаты'))
    fireEvent.click(await screen.findByTitle('Наличные'))
    await waitFor(() => expect(listVendorsMock).toHaveBeenCalledWith({ kind: 'cash', search: '' }))

    fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }))
    expect(await screen.findByText('Укажите поставщика')).toBeInTheDocument()
    expect(onSave).not.toHaveBeenCalled()
  })

  it('takes the category from the chosen payment purpose', async () => {
    const { onSave } = renderModal({
      paymentTypeConfigs: [
        {
          payment_type: 'Перечисление',
          requester_ids: [],
          requesters: [],
          vendor_ids: [],
          payment_purposes: [
            { name: 'Покупка оборудования', category: 'Оборудование' },
            { name: 'Аренда', category: 'Аренда помещений' },
          ],
        },
      ],
      initialDraft: requestEditDraftFromDetail({ ...detail, payment_purpose: 'Покупка оборудования' }),
    })

    fireEvent.mouseDown(await screen.findByLabelText('Назначение платежа'))
    fireEvent.click(await screen.findByTitle('Аренда'))
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }))

    expect(onSave.mock.calls[0][0]).toMatchObject({ payment_purpose: 'Аренда', category: 'Аренда помещений' })
  })

  it('shows the status read-only, since it changes only through approval', async () => {
    renderModal()
    const status = await screen.findByLabelText('Статус')
    expect(status).toBeDisabled()
    expect(status).toHaveValue('Оплачена')
  })

  it('loads vendors from the directory of the request payment type', async () => {
    renderModal()
    await waitFor(() => expect(listVendorsMock).toHaveBeenCalledWith({ kind: 'transfer', search: '' }))
  })
})

describe('requestEditDraftFromDetail', () => {
  it('turns amortization months into the switch and month count', () => {
    expect(requestEditDraftFromDetail({ ...detail, amortization_months: 4 })).toMatchObject({
      amortization_enabled: true,
      amortization_months: 4,
    })
    expect(requestEditDraftFromDetail(detail)).toMatchObject({ amortization_enabled: false, amortization_months: 2 })
  })
})
