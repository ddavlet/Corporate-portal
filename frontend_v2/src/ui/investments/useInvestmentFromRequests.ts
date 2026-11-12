import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { message } from 'antd'

import {
  createInvestmentsFromRequests,
  getFundingPool,
  type FundingPoolDto,
  type ProjectInvestmentRow,
} from '../../lib/api'
import { defaultCollectComment, totalsByCurrency, type FundingMethod } from './fundingPool'

/**
 * «Вложение по заявкам» without its markup: the desktop modal and the phone wizard. The pool loads on mount with every
 * request of both funding methods selected. The description is only a preview until the user edits it (the server
 * then writes its own per currency, `comment: ''`); switching the method drops the edit. `submit` sends nothing while
 * a request is in flight or once the investments are created (`created`), so a double tap or a way back to the
 * last step cannot create them twice.
 */
export function useInvestmentFromRequests() {
  const [pool, setPool] = useState<FundingPoolDto | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [loadKey, setLoadKey] = useState(0)
  const [method, setMethodState] = useState<FundingMethod>('cash')
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [editedComment, setEditedComment] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [created, setCreated] = useState<ProjectInvestmentRow[] | null>(null)
  const submittingRef = useRef(false)
  const createdRef = useRef(false)

  useEffect(() => {
    let cancelled = false
    getFundingPool()
      .then((data) => {
        if (cancelled) return
        setPool(data)
        setSelected(new Set([...data.cash.requests, ...data.bank_transfer.requests].map((r) => r.id)))
      })
      .catch((e: unknown) => {
        if (!cancelled) setLoadError(e instanceof Error ? e.message : 'Не удалось загрузить заявки')
      })
    return () => {
      cancelled = true
    }
  }, [loadKey])

  const reload = useCallback(() => {
    setLoadError(null)
    setPool(null)
    setLoadKey((k) => k + 1)
  }, [])

  const setMethod = useCallback((next: FundingMethod) => {
    setMethodState(next)
    setEditedComment(null)
  }, [])

  const toggleOne = useCallback((id: number) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }, [])

  /** Replaces the selection among `ids` (one table of the desktop modal) with `keys`. */
  const replaceSelection = useCallback((ids: number[], keys: number[]) => {
    setSelected((prev) => {
      const next = new Set(prev)
      ids.forEach((id) => next.delete(id))
      keys.forEach((k) => next.add(k))
      return next
    })
  }, [])

  const rows = useMemo(() => (pool ? pool[method].requests : []), [pool, method])
  const chosen = useMemo(() => rows.filter((r) => selected.has(r.id)), [rows, selected])
  const totals = useMemo(() => totalsByCurrency(rows, selected), [rows, selected])
  const generated = useMemo(() => defaultCollectComment(chosen), [chosen])
  const comment = editedComment ?? generated
  const setComment = useCallback((value: string) => setEditedComment(value), [])

  const submit = async (): Promise<ProjectInvestmentRow[] | null> => {
    if (submittingRef.current || createdRef.current || chosen.length === 0) return null
    submittingRef.current = true
    setSubmitting(true)
    try {
      const result = await createInvestmentsFromRequests({
        funding_method: method,
        request_ids: chosen.map((r) => r.id),
        // The default text is only a preview: an empty comment makes the server write the description per currency.
        comment: editedComment ?? '',
      })
      createdRef.current = true
      setCreated(result.investments)
      message.success(`Создано вложений: ${result.investments.map((i) => `№${i.id}`).join(', ')}`)
      return result.investments
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : 'Не удалось создать вложение')
      return null
    } finally {
      submittingRef.current = false
      setSubmitting(false)
    }
  }

  return {
    pool,
    loading: !pool && !loadError,
    loadError,
    reload,
    method,
    setMethod,
    selected,
    toggleOne,
    replaceSelection,
    rows,
    chosen,
    totals,
    generated,
    comment,
    setComment,
    canSubmit: chosen.length > 0 && !submitting && !created,
    submitting,
    created,
    submit,
  }
}

export type InvestmentFromRequestsState = ReturnType<typeof useInvestmentFromRequests>
