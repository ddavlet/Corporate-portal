import { useCallback, useEffect, useMemo, useRef, useState, type SetStateAction } from 'react'
import { getUserPreferences, setUserPreference } from './api'

type UseUserPreferenceOptions<T> = {
  key: string
  defaultValue: T
  debounceMs?: number
  normalize?: (raw: unknown, fallback: T) => T
  onError?: (error: Error) => void
}

export function useUserPreference<T>({
  key,
  defaultValue,
  debounceMs = 300,
  normalize,
  onError,
}: UseUserPreferenceOptions<T>) {
  const [value, setValue] = useState<T>(defaultValue)
  const [isLoading, setIsLoading] = useState(true)
  const [isReady, setIsReady] = useState(false)
  const writeSeqRef = useRef(0)
  const timerRef = useRef<number | null>(null)
  const hasLoadedRef = useRef(false)

  const normalizeValue = useMemo(
    () =>
      normalize ??
      ((raw: unknown, fallback: T) => {
        if (raw === undefined) return fallback
        return raw as T
      }),
    [normalize],
  )

  useEffect(() => {
    hasLoadedRef.current = false
    setIsLoading(true)
    setIsReady(false)
    let cancelled = false
    ;(async () => {
      try {
        const prefs = await getUserPreferences([key])
        if (cancelled) return
        setValue(normalizeValue(prefs[key], defaultValue))
      } catch (error: unknown) {
        if (!cancelled && onError && error instanceof Error) onError(error)
      } finally {
        if (!cancelled) {
          hasLoadedRef.current = true
          setIsLoading(false)
          setIsReady(true)
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [key, defaultValue, normalizeValue, onError])

  useEffect(() => {
    if (!isReady || !hasLoadedRef.current) return
    if (timerRef.current != null) {
      window.clearTimeout(timerRef.current)
      timerRef.current = null
    }
    const seq = ++writeSeqRef.current
    timerRef.current = window.setTimeout(() => {
      void (async () => {
        try {
          await setUserPreference(key, value)
        } catch (error: unknown) {
          if (seq !== writeSeqRef.current) return
          if (onError && error instanceof Error) onError(error)
        }
      })()
    }, debounceMs)
    return () => {
      if (timerRef.current != null) {
        window.clearTimeout(timerRef.current)
        timerRef.current = null
      }
    }
  }, [key, value, debounceMs, isReady, onError])

  const updateValue = useCallback((next: SetStateAction<T>) => {
    setValue(next)
  }, [])

  return { value, setValue: updateValue, isLoading }
}
