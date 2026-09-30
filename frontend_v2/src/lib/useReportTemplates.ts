import { useCallback, useEffect, useState } from 'react'
import { getReportTemplates, type ReportTemplatesResponse } from './reportsApi'

type TemplatesLoad = { templates: ReportTemplatesResponse | null; failed: boolean; loading: boolean }

export type ReportTemplatesState = TemplatesLoad & {
  /** Asks the server again, for a page that shows the failure. */
  retry: () => void
}

/**
 * One request per session: the cards page and every report page read the same list,
 * so moving from a card to its report shows no second loading state.
 */
let cachedPromise: Promise<ReportTemplatesResponse> | null = null
let cachedValue: ReportTemplatesResponse | null = null

function fetchTemplates(): Promise<ReportTemplatesResponse> {
  if (!cachedPromise) {
    cachedPromise = getReportTemplates().then(
      (value) => {
        cachedValue = value
        return value
      },
      (error: unknown) => {
        // A failure is not cached: the next page asks again.
        cachedPromise = null
        throw error
      },
    )
  }
  return cachedPromise
}

/** Called after the admin saves template settings, and on login and logout. */
export function resetReportTemplatesCache(): void {
  cachedPromise = null
  cachedValue = null
}

export function useReportTemplates(): ReportTemplatesState {
  const [attempt, setAttempt] = useState(0)
  const [state, setState] = useState<TemplatesLoad>(() =>
    cachedValue
      ? { templates: cachedValue, failed: false, loading: false }
      : { templates: null, failed: false, loading: true },
  )

  useEffect(() => {
    let active = true
    fetchTemplates()
      .then((templates) => {
        if (active) setState({ templates, failed: false, loading: false })
      })
      .catch(() => {
        if (active) setState({ templates: null, failed: true, loading: false })
      })
    return () => {
      active = false
    }
  }, [attempt])

  const retry = useCallback(() => {
    setState({ templates: null, failed: false, loading: true })
    setAttempt((count) => count + 1)
  }, [])

  return { ...state, retry }
}
