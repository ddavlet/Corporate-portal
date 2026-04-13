import { useCallback, useEffect, useRef, useState, type SetStateAction } from 'react'
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
  const fallbackNormalize = useCallback((raw: unknown, fallback: T) => {
    if (raw === undefined) return fallback
    return raw as T
  }, [])
  const [value, setValue] = useState<T>(defaultValue)
  const [isLoading, setIsLoading] = useState(true)
  const [isReady, setIsReady] = useState(false)
  const writeSeqRef = useRef(0)
  const timerRef = useRef<number | null>(null)
  const hasLoadedRef = useRef(false)
  const normalizeRef = useRef<typeof normalize>(normalize)
  const defaultValueRef = useRef(defaultValue)
  const onErrorRef = useRef<typeof onError>(onError)

  useEffect(() => {
    normalizeRef.current = normalize
  }, [normalize])

  useEffect(() => {
    defaultValueRef.current = defaultValue
  }, [defaultValue])

  useEffect(() => {
    onErrorRef.current = onError
  }, [onError])

  useEffect(() => {
    hasLoadedRef.current = false
    setIsLoading(true)
    setIsReady(false)
    let cancelled = false
    ;(async () => {
      try {
        const prefs = await getUserPreferences([key])
        if (cancelled) return
        const normalizeValue = normalizeRef.current ?? fallbackNormalize
        setValue(normalizeValue(prefs[key], defaultValueRef.current))
      } catch (error: unknown) {
        if (!cancelled && onErrorRef.current && error instanceof Error) onErrorRef.current(error)
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
  }, [key, fallbackNormalize])

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
          if (onErrorRef.current && error instanceof Error) onErrorRef.current(error)
        }
      })()
    }, debounceMs)
    return () => {
      if (timerRef.current != null) {
        window.clearTimeout(timerRef.current)
        timerRef.current = null
      }
    }
  }, [key, value, debounceMs, isReady])

  const updateValue = useCallback((next: SetStateAction<T>) => {
    setValue(next)
  }, [])

  return { value, setValue: updateValue, isLoading }
}
