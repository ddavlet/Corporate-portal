import { useCallback, useEffect, useRef, useState } from 'react'
import { message } from 'antd'

import {
  getCashBalances,
  getCashRegisters,
  getSettingsAccess,
  type CashRegisterDto,
  type ChannelBalanceRow,
} from '../lib/api'
import {
  CashRegisterTransferTargetError,
  cashRegisterLabel,
  cashRegisterTransferErrorText,
  submitCashRegisterTransfer,
} from '../lib/cashRegisterTransfer'

/** Values of the phone «Перевод между кассами» form; the same fields as the desktop modal and the Mini App page. */
export type CashRegisterTransferFormValues = {
  fromId: number | null
  toId: number | null
  amount: number | null
  /** Sum credited to the target register; asked for only when the registers have different currencies. */
  toAmount: number | null
  note: string
}

export type CashRegisterTransferField = 'fromId' | 'toId' | 'amount' | 'toAmount'

export type CashRegisterTransferFieldErrors = Partial<Record<CashRegisterTransferField, string>>

/**
 * `created` — the request is sent for approval; `target_error` — it is on approval but the target register was not
 * saved (a warning is shown, the form must be left so a second «Отправить» does not create another request);
 * `failed` — the error is shown on the form, the values are kept; `invalid` — field errors; `busy` — already sending.
 */
export type CashRegisterTransferSubmitResult = 'created' | 'target_error' | 'failed' | 'invalid' | 'busy'

export const CASH_REGISTER_TRANSFER_SUCCESS_TEXT = 'Заявка на перевод создана и отправлена на согласование'

export const cashRegisterTransferDefaults = (): CashRegisterTransferFormValues => ({
  fromId: null,
  toId: null,
  amount: null,
  toAmount: null,
  note: '',
})

const isPositive = (v: number | null): v is number => typeof v === 'number' && Number.isFinite(v) && v > 0

/** Balance of one register now and after the transfer; `after` is null until a sum is entered. */
export type CashRegisterBalancePreview = {
  currency: string
  current: number
  after: number | null
  /** Signed change: negative for the source, positive for the target. */
  delta: number | null
}

/** Current balance of the register from GET /api/cash/balances/, or null when it is not there. */
export function findCashRegisterBalance(rows: ChannelBalanceRow[], register: CashRegisterDto): number | null {
  const row =
    rows.find((r) => r.cash_register_id === register.id) ?? rows.find((r) => r.wallet_id === register.wallet_id)
  if (!row) return null
  const n = Number(row.current_balance)
  return Number.isFinite(n) ? n : null
}

const round2 = (n: number) => Math.round(n * 100) / 100

export function cashRegisterBalancePreview(
  register: CashRegisterDto | null,
  rows: ChannelBalanceRow[] | null,
  delta: number | null,
): CashRegisterBalancePreview | null {
  if (!register || !rows) return null
  const current = findCashRegisterBalance(rows, register)
  if (current == null) return null
  const d = typeof delta === 'number' && Number.isFinite(delta) && delta !== 0 ? delta : null
  return { currency: register.currency, current, after: d == null ? null : round2(current + d), delta: d }
}

/** «1234567.5» → «1 234 567.5»: digit groups for the sum inputs, so a missing or extra zero is seen at once. */
export function formatAmountInput(value: string | number | undefined): string {
  if (value === undefined || value === null || value === '') return ''
  const [int, frac] = String(value).split('.')
  const grouped = int.replace(/\B(?=(\d{3})+(?!\d))/g, ' ')
  return frac === undefined ? grouped : `${grouped}.${frac}`
}

/**
 * Back from the input: drops the group spaces; «50,000» (a comma before exactly three digits) is a digit group, as
 * people type thousands; any other «,» is the decimal point (the iOS keypad in ru gives «1,5»).
 */
export function parseAmountInput(value: string | undefined): string {
  const compact = (value ?? '').replace(/[\s\u00a0\u202f]/g, '')
  if (/^-?\d{1,3}(,\d{3})+$/.test(compact)) return compact.replace(/,/g, '')
  return compact.replace(',', '.')
}

/** Errors of the form, with the rules of the desktop modal; empty when it can be sent. */
export function validateCashRegisterTransferValues(
  v: CashRegisterTransferFormValues,
  currencyMismatch: boolean,
): CashRegisterTransferFieldErrors {
  const errors: CashRegisterTransferFieldErrors = {}
  if (v.fromId == null) errors.fromId = 'Выберите кассу-источник'
  if (v.toId == null) errors.toId = 'Выберите кассу-назначение'
  else if (v.toId === v.fromId) errors.toId = 'Касса-назначение должна отличаться от кассы-источника'
  if (!isPositive(v.amount)) errors.amount = 'Укажите сумму'
  if (currencyMismatch && !isPositive(v.toAmount)) errors.toAmount = 'Укажите сумму зачисления'
  return errors
}

/**
 * State and sending of the phone transfer between cash registers: loads the active registers and the requester,
 * keeps the values, the field errors and the server's error, and sends only through submitCashRegisterTransfer.
 * A repeated submit while one is in flight is dropped (a ref, not only the button's state).
 */
export function useCashRegisterTransferForm() {
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [reloadKey, setReloadKey] = useState(0)
  const [registers, setRegisters] = useState<CashRegisterDto[]>([])
  const [requesterId, setRequesterId] = useState<number | null>(null)
  // null — not loaded (or failed): the form works without the balances, they are only a hint.
  const [balances, setBalances] = useState<ChannelBalanceRow[] | null>(null)
  const [values, setValues] = useState<CashRegisterTransferFormValues>(cashRegisterTransferDefaults)
  const [errors, setErrors] = useState<CashRegisterTransferFieldErrors>({})
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const submittingRef = useRef(false)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setLoadError(null)
    Promise.all([getCashRegisters(), getSettingsAccess()])
      .then(([rows, access]) => {
        if (cancelled) return
        setRegisters(rows.filter((r) => r.is_active))
        setRequesterId(typeof access.user_id === 'number' ? access.user_id : null)
      })
      .catch((e: unknown) => {
        if (!cancelled) setLoadError(e instanceof Error ? e.message : 'Не удалось загрузить список касс')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    getCashBalances()
      .then((rows) => {
        if (!cancelled) setBalances(rows)
      })
      .catch((e: unknown) => {
        if (!cancelled) setBalances(null)
        console.warn('cash transfer: balances not loaded', e)
      })
    return () => {
      cancelled = true
    }
  }, [reloadKey])

  const reload = useCallback(() => setReloadKey((k) => k + 1), [])

  const fromRegister = registers.find((r) => r.id === values.fromId) ?? null
  const toRegister = registers.find((r) => r.id === values.toId) ?? null
  const currencyMismatch = Boolean(fromRegister && toRegister && fromRegister.currency !== toRegister.currency)
  const toDelta = currencyMismatch ? values.toAmount : values.amount
  const fromBalance = cashRegisterBalancePreview(fromRegister, balances, values.amount == null ? null : -values.amount)
  const toBalance = cashRegisterBalancePreview(toRegister, balances, toDelta)
  const fromOptions = registers
    .filter((r) => r.id !== values.toId)
    .map((r) => ({ value: r.id, label: cashRegisterLabel(r) }))
  const toOptions = registers
    .filter((r) => r.id !== values.fromId)
    .map((r) => ({ value: r.id, label: cashRegisterLabel(r) }))

  const update = <K extends keyof CashRegisterTransferFormValues>(key: K, value: CashRegisterTransferFormValues[K]) => {
    setValues((prev) => ({ ...prev, [key]: value }))
    if (key === 'note') return
    setErrors((prev) => {
      if (!(key in prev)) return prev
      const next = { ...prev }
      delete next[key as CashRegisterTransferField]
      return next
    })
  }

  const submit = async (): Promise<CashRegisterTransferSubmitResult> => {
    if (submittingRef.current) return 'busy'
    const found = validateCashRegisterTransferValues(values, currencyMismatch)
    if (Object.keys(found).length > 0 || !fromRegister || !toRegister || values.amount == null) {
      setErrors(found)
      return 'invalid'
    }
    setErrors({})
    setSubmitError(null)
    submittingRef.current = true
    setSubmitting(true)
    try {
      await submitCashRegisterTransfer({
        fromRegister,
        toRegister,
        amount: values.amount,
        note: values.note,
        toAmount: currencyMismatch && values.toAmount != null ? values.toAmount : undefined,
        requesterId,
      })
      message.success(CASH_REGISTER_TRANSFER_SUCCESS_TEXT)
      return 'created'
    } catch (err: unknown) {
      if (err instanceof CashRegisterTransferTargetError) {
        message.warning(cashRegisterTransferErrorText(err), 10)
        return 'target_error'
      }
      setSubmitError(cashRegisterTransferErrorText(err))
      return 'failed'
    } finally {
      submittingRef.current = false
      setSubmitting(false)
    }
  }

  return {
    loading,
    loadError,
    reload,
    registers,
    values,
    errors,
    submitError,
    submitting,
    fromRegister,
    toRegister,
    currencyMismatch,
    fromBalance,
    toBalance,
    fromOptions,
    toOptions,
    setFromId: (v: number | null) => update('fromId', v),
    setToId: (v: number | null) => update('toId', v),
    setAmount: (v: number | null) => update('amount', v),
    setToAmount: (v: number | null) => update('toAmount', v),
    setNote: (v: string) => update('note', v),
    submit,
  }
}
