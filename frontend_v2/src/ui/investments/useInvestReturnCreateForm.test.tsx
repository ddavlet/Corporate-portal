import { act, renderHook } from '@testing-library/react'
import { message } from 'antd'
import dayjs from 'dayjs'
import timezone from 'dayjs/plugin/timezone'
import utc from 'dayjs/plugin/utc'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { DEFAULT_INVESTMENT_FORM_CONFIG } from '../../lib/api'
import {
  investReturnDefaults,
  returnTypeOptionsFromConfig,
  useInvestReturnCreateForm,
  validateInvestReturnValues,
  type InvestReturnFormValues,
} from './useInvestReturnCreateForm'

// main.tsx extends dayjs in the app; the accrual month defaults need .tz() (tashkentTime).
dayjs.extend(utc)
dayjs.extend(timezone)

const api = vi.hoisted(() => ({ createInvestReturn: vi.fn() }))

vi.mock('../../lib/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../lib/api')>()),
  createInvestReturn: (...a: unknown[]) => api.createInvestReturn(...a),
}))

const TYPES = [
  { value: 'return_of_funds', label: 'Возврат средств' },
  { value: 'dividend', label: 'Дивиденды' },
]

function deferred<T>() {
  let resolve!: (v: T) => void
  const promise = new Promise<T>((res) => {
    resolve = res
  })
  return { promise, resolve }
}

function filled(over: Partial<InvestReturnFormValues> = {}): InvestReturnFormValues {
  return { ...investReturnDefaults(TYPES), sum: 1500, ...over }
}

let successSpy: ReturnType<typeof vi.spyOn>
let errorSpy: ReturnType<typeof vi.spyOn>
let warningSpy: ReturnType<typeof vi.spyOn>

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] })
  // 25 ноября 2026, 12:00 по Ташкенту.
  vi.setSystemTime(new Date('2026-11-25T07:00:00Z'))
  api.createInvestReturn.mockReset().mockResolvedValue({})
  successSpy = vi.spyOn(message, 'success').mockImplementation(() => undefined as never)
  errorSpy = vi.spyOn(message, 'error').mockImplementation(() => undefined as never)
  warningSpy = vi.spyOn(message, 'warning').mockImplementation(() => undefined as never)
})

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('investReturnDefaults', () => {
  it('takes today, the current month, USD, the first type and the investor on the 25th', () => {
    const v = investReturnDefaults(TYPES)
    expect(v.date?.format('YYYY-MM-DD')).toBe('2026-11-25')
    expect(v.billing_date?.format('YYYY-MM-DD')).toBe('2026-11-01')
    expect(v).toMatchObject({ sum: null, currency: 'USD', type: 'return_of_funds', recipient: 'инвестор', comment: '' })
  })

  it('takes the current month on the 12th too', () => {
    vi.setSystemTime(new Date('2026-11-12T07:00:00Z'))
    const v = investReturnDefaults(TYPES)
    expect(v.date?.format('YYYY-MM-DD')).toBe('2026-11-12')
    expect(v.billing_date?.format('YYYY-MM-DD')).toBe('2026-11-01')
  })

  it('falls back to «дивиденды» without allowed types', () => {
    expect(investReturnDefaults([]).type).toBe('дивиденды')
  })
})

describe('returnTypeOptionsFromConfig', () => {
  it('keeps only the allowed types in the order of the choices', () => {
    expect(
      returnTypeOptionsFromConfig({
        allowed_return_types: ['тело_инвестиций', 'проценты'],
        return_type_choices: DEFAULT_INVESTMENT_FORM_CONFIG.return_type_choices,
      }),
    ).toEqual([
      { value: 'проценты', label: 'Проценты' },
      { value: 'тело_инвестиций', label: 'Тело инвестиций' },
    ])
  })
})

describe('validateInvestReturnValues', () => {
  it('passes a filled form', () => {
    expect(validateInvestReturnValues(filled())).toEqual({})
  })

  it('names every empty required field', () => {
    expect(
      validateInvestReturnValues({
        date: null,
        billing_date: null,
        sum: null,
        currency: '',
        type: '',
        recipient: '',
      }),
    ).toEqual({
      billing_date: 'Укажите месяц начисления',
      date: 'Укажите дату',
      sum: 'Укажите сумму',
      currency: 'Выберите валюту',
      type: 'Выберите тип',
      recipient: 'Выберите получателя',
    })
  })

  it('refuses a month that is not allowed any more', () => {
    // С 21-го прошлый месяц закрыт.
    expect(validateInvestReturnValues(filled({ billing_date: dayjs.tz('2026-10-15', 'Asia/Tashkent') }))).toEqual({
      billing_date: 'Выберите допустимый месяц начисления',
    })
  })
})

describe('useInvestReturnCreateForm', () => {
  it('sends the desktop payload, reports success and calls onCreated', async () => {
    const onCreated = vi.fn().mockResolvedValue(undefined)
    const { result } = renderHook(() => useInvestReturnCreateForm({ onCreated }))

    let outcome: string | undefined
    await act(async () => {
      outcome = await result.current.submit(filled({ comment: undefined }))
    })

    expect(outcome).toBe('created')
    expect(api.createInvestReturn).toHaveBeenCalledTimes(1)
    expect(api.createInvestReturn.mock.calls[0][0]).toEqual({
      date: '2026-11-25',
      billing_date: '2026-11-01',
      sum: '1500',
      currency: 'USD',
      type: 'return_of_funds',
      recipient: 'инвестор',
      comment: '',
    })
    expect(successSpy).toHaveBeenCalledWith('Выплата создана и отправлена на согласование')
    expect(onCreated).toHaveBeenCalledTimes(1)
    expect(result.current.submitting).toBe(false)
  })

  it('answers «busy» to a second call while the first is in flight', async () => {
    const pending = deferred<unknown>()
    api.createInvestReturn.mockReturnValue(pending.promise)
    const { result } = renderHook(() => useInvestReturnCreateForm({ onCreated: () => undefined }))

    let first!: Promise<string>
    let second: string | undefined
    await act(async () => {
      first = result.current.submit(filled())
      second = await result.current.submit(filled())
    })
    expect(second).toBe('busy')
    expect(result.current.submitting).toBe(true)

    await act(async () => {
      pending.resolve({})
      await first
    })
    expect(await first).toBe('created')
    expect(api.createInvestReturn).toHaveBeenCalledTimes(1)
  })

  it('returns «invalid_month» without a request and without any message', async () => {
    const onCreated = vi.fn()
    const { result } = renderHook(() => useInvestReturnCreateForm({ onCreated }))

    let outcome: string | undefined
    await act(async () => {
      outcome = await result.current.submit(filled({ billing_date: dayjs.tz('2026-10-15', 'Asia/Tashkent') }))
    })

    expect(outcome).toBe('invalid_month')
    expect(api.createInvestReturn).not.toHaveBeenCalled()
    expect(warningSpy).not.toHaveBeenCalled()
    expect(errorSpy).not.toHaveBeenCalled()
    expect(onCreated).not.toHaveBeenCalled()
  })

  it('reports the server error and returns «failed»', async () => {
    api.createInvestReturn.mockRejectedValue(new Error('Сервер отклонил выплату'))
    const onCreated = vi.fn()
    const { result } = renderHook(() => useInvestReturnCreateForm({ onCreated }))

    let outcome: string | undefined
    await act(async () => {
      outcome = await result.current.submit(filled())
    })

    expect(outcome).toBe('failed')
    expect(errorSpy).toHaveBeenCalledWith('Сервер отклонил выплату')
    expect(successSpy).not.toHaveBeenCalled()
    expect(onCreated).not.toHaveBeenCalled()
    expect(result.current.submitting).toBe(false)
  })
})
