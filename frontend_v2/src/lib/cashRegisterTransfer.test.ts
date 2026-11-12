import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { CashRegisterDto } from './api'
import {
  CashRegisterTransferSubmitError,
  CashRegisterTransferTargetError,
  cashRegisterTransferErrorText,
  generalFormPurposes,
  isCashRegisterTransferPurpose,
  submitCashRegisterTransfer,
} from './cashRegisterTransfer'

const createPortalRequestMock = vi.fn()
const submitRequestForApprovalMock = vi.fn()
const setTargetMock = vi.fn()

vi.mock('./api', () => ({
  createPortalRequest: (...args: unknown[]) => createPortalRequestMock(...args),
  submitRequestForApproval: (...args: unknown[]) => submitRequestForApprovalMock(...args),
}))

vi.mock('./cashDeskApi', () => ({
  setCashRegisterTransferTarget: (...args: unknown[]) => setTargetMock(...args),
}))

function register(over: Partial<CashRegisterDto>): CashRegisterDto {
  return {
    id: 1,
    tenant: 1,
    currency: 'UZS',
    name: 'Касса А',
    code: '',
    description: '',
    is_active: true,
    sort_order: 0,
    is_default_for_currency: false,
    wallet_id: 101,
    ...over,
  }
}

const UZS_A = register({})
const UZS_B = register({ id: 2, name: 'Касса Б', wallet_id: 102 })
const USD = register({ id: 3, name: 'Касса USD', currency: 'USD', wallet_id: 103 })

describe('submitCashRegisterTransfer', () => {
  beforeEach(() => {
    createPortalRequestMock.mockReset().mockResolvedValue({ id: 777 })
    submitRequestForApprovalMock.mockReset().mockResolvedValue({})
    setTargetMock.mockReset().mockResolvedValue(undefined)
  })

  it('calls target before submit', async () => {
    const order: string[] = []
    createPortalRequestMock.mockImplementation(async () => {
      order.push('create')
      return { id: 777 }
    })
    setTargetMock.mockImplementation(async () => {
      order.push('target')
    })
    submitRequestForApprovalMock.mockImplementation(async () => {
      order.push('submit')
    })

    await submitCashRegisterTransfer({ fromRegister: UZS_A, toRegister: UZS_B, amount: 1000 })

    expect(order).toEqual(['create', 'target', 'submit'])
    expect(setTargetMock).toHaveBeenCalledWith(777, { to_wallet_id: 102 })
  })

  it('request already on approval after create: saves target, does not submit again', async () => {
    createPortalRequestMock.mockResolvedValueOnce({ id: 777, status: '1' })

    await expect(
      submitCashRegisterTransfer({ fromRegister: UZS_A, toRegister: UZS_B, amount: 1000 }),
    ).resolves.toEqual({ id: 777 })

    expect(setTargetMock).toHaveBeenCalledWith(777, { to_wallet_id: 102 })
    expect(submitRequestForApprovalMock).not.toHaveBeenCalled()
  })

  it('draft after create is submitted', async () => {
    createPortalRequestMock.mockResolvedValueOnce({ id: 777, status: 'DRAFT' })

    await submitCashRegisterTransfer({ fromRegister: UZS_A, toRegister: UZS_B, amount: 1000 })

    expect(submitRequestForApprovalMock).toHaveBeenCalledWith(777)
  })

  it('target failure after auto-submit throws CashRegisterTransferTargetError', async () => {
    createPortalRequestMock.mockResolvedValueOnce({ id: 777, status: '1' })
    setTargetMock.mockRejectedValueOnce(new Error('Заявка уже оплачена или закрыта.'))

    const err = await submitCashRegisterTransfer({
      fromRegister: UZS_A,
      toRegister: UZS_B,
      amount: 1000,
    }).catch((e: unknown) => e)

    expect(err).toBeInstanceOf(CashRegisterTransferTargetError)
    expect((err as CashRegisterTransferTargetError).requestId).toBe(777)
    expect(cashRegisterTransferErrorText(err)).toBe(
      'Заявка №777 отправлена на согласование, но касса-получатель не сохранена (Заявка уже оплачена или закрыта). ' +
        'Если после оплаты приход не появится, внесите его вручную.',
    )
    expect(submitRequestForApprovalMock).not.toHaveBeenCalled()
  })

  it('sends to_amount only for different currencies', async () => {
    await submitCashRegisterTransfer({ fromRegister: UZS_A, toRegister: USD, amount: 1000, toAmount: 80 })

    expect(setTargetMock).toHaveBeenCalledWith(777, { to_wallet_id: 103, to_amount: 80 })
    const description = createPortalRequestMock.mock.calls[0][0].description as string
    expect(description).toContain('Сумма зачисления: 80 USD')

    setTargetMock.mockClear()
    await submitCashRegisterTransfer({ fromRegister: UZS_A, toRegister: UZS_B, amount: 1000, toAmount: 5 })
    expect(setTargetMock).toHaveBeenCalledWith(777, { to_wallet_id: 102 })
  })

  it('rejects cross-currency without toAmount', async () => {
    await expect(
      submitCashRegisterTransfer({ fromRegister: UZS_A, toRegister: USD, amount: 1000 }),
    ).rejects.toThrow('Укажите сумму зачисления')
    expect(createPortalRequestMock).not.toHaveBeenCalled()
  })

  it('target failure throws CashRegisterTransferSubmitError with requestId', async () => {
    setTargetMock.mockRejectedValueOnce(new Error('boom'))

    const err = await submitCashRegisterTransfer({
      fromRegister: UZS_A,
      toRegister: UZS_B,
      amount: 1000,
    }).catch((e: unknown) => e)

    expect(err).toBeInstanceOf(CashRegisterTransferSubmitError)
    expect((err as CashRegisterTransferSubmitError).requestId).toBe(777)
    expect(submitRequestForApprovalMock).not.toHaveBeenCalled()
  })

  it('module unavailable (404) with same currency still submits', async () => {
    setTargetMock.mockRejectedValueOnce(Object.assign(new Error('Not found'), { status: 404 }))

    await expect(
      submitCashRegisterTransfer({ fromRegister: UZS_A, toRegister: UZS_B, amount: 1000 }),
    ).resolves.toEqual({ id: 777 })
    expect(submitRequestForApprovalMock).toHaveBeenCalledWith(777)
  })

  it('module unavailable (404) with different currencies throws', async () => {
    setTargetMock.mockRejectedValueOnce(Object.assign(new Error('Not found'), { status: 404 }))

    const err = await submitCashRegisterTransfer({
      fromRegister: UZS_A,
      toRegister: USD,
      amount: 1000,
      toAmount: 80,
    }).catch((e: unknown) => e)

    expect(err).toBeInstanceOf(CashRegisterTransferSubmitError)
    expect((err as CashRegisterTransferSubmitError).requestId).toBe(777)
    expect(submitRequestForApprovalMock).not.toHaveBeenCalled()
  })

  it('non-404 target failure with same currency throws', async () => {
    setTargetMock.mockRejectedValueOnce(Object.assign(new Error('Server error'), { status: 500 }))

    const err = await submitCashRegisterTransfer({
      fromRegister: UZS_A,
      toRegister: UZS_B,
      amount: 1000,
    }).catch((e: unknown) => e)

    expect(err).toBeInstanceOf(CashRegisterTransferSubmitError)
    expect(submitRequestForApprovalMock).not.toHaveBeenCalled()
  })
})

describe('generalFormPurposes', () => {
  it('hides the cash-register transfer purpose and reports it', () => {
    const { purposes, transferHidden } = generalFormPurposes([
      { name: 'Хозтовары', category: 'Хоз' },
      { name: 'Перевод между кассами', category: 'Перевод между кассами' },
    ])
    expect(purposes.map((p) => p.name)).toEqual(['Хозтовары'])
    expect(transferHidden).toBe(true)
  })

  it('keeps other purposes untouched', () => {
    expect(generalFormPurposes([{ name: 'Хозтовары' }])).toEqual({
      purposes: [{ name: 'Хозтовары' }],
      transferHidden: false,
    })
    expect(generalFormPurposes(undefined)).toEqual({ purposes: [], transferHidden: false })
    expect(generalFormPurposes([{ name: 'Перевод между кассами' }])).toEqual({ purposes: [], transferHidden: true })
  })

  it('matches the purpose name ignoring surrounding spaces', () => {
    expect(isCashRegisterTransferPurpose(' Перевод между кассами ')).toBe(true)
    expect(isCashRegisterTransferPurpose('Перевод')).toBe(false)
    expect(isCashRegisterTransferPurpose(null)).toBe(false)
  })
})
