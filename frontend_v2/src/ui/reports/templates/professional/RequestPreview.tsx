import { useCallback, useRef, useState, type ReactNode } from 'react'
import { describeReportError } from '../../../../lib/reportErrors'
import { getReportRequestDetail } from '../../../../lib/reportsApi'
import { RequestDetailModal, type RequestDetail } from '../../../requests/RequestDetailModal'

/**
 * Above the report's drawers (z-index 1000). antd keeps a popup's container in the page once it has opened,
 * so with equal z-index a card first opened from «Операции» would later appear under the drill-down panel.
 */
const REQUEST_PREVIEW_Z_INDEX = 1100

/** Opens a request card on top of the report without leaving the page. */
export function useRequestPreview(): { open: (requestId: number) => void; modal: ReactNode } {
  const [requestId, setRequestId] = useState<number | null>(null)
  const [detail, setDetail] = useState<RequestDetail | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // Only the request opened last may fill the card; a slower earlier answer is dropped.
  const latest = useRef<number | null>(null)

  const open = useCallback((id: number) => {
    latest.current = id
    setRequestId(id)
    setDetail(null)
    setError(null)
    setLoading(true)
    getReportRequestDetail(id)
      .then((json) => {
        if (latest.current === id) setDetail(json as RequestDetail)
      })
      .catch((e: unknown) => {
        if (latest.current === id) setError(describeReportError(e, 'Не удалось загрузить заявку'))
      })
      .finally(() => {
        if (latest.current === id) setLoading(false)
      })
  }, [])

  const modal = (
    <RequestDetailModal open={requestId !== null} onCancel={() => setRequestId(null)} detail={detail} loading={loading} error={error} zIndex={REQUEST_PREVIEW_Z_INDEX} />
  )
  return { open, modal }
}
