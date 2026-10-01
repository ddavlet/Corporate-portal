import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const getReportTemplatesMock = vi.fn()
vi.mock('./reportsApi', () => ({ getReportTemplates: () => getReportTemplatesMock() }))

import { resetReportTemplatesCache, useReportTemplates } from './useReportTemplates'

const TEMPLATES = { default: 'classic', allowed: [], available: [] }

describe('useReportTemplates', () => {
  beforeEach(() => {
    resetReportTemplatesCache()
    getReportTemplatesMock.mockReset()
  })

  it('asks the server once for every page of the session and answers the next page at once', async () => {
    getReportTemplatesMock.mockResolvedValue(TEMPLATES)
    const first = renderHook(() => useReportTemplates())
    await waitFor(() => expect(first.result.current).toMatchObject({ templates: TEMPLATES, failed: false, loading: false }))
    const second = renderHook(() => useReportTemplates())
    expect(second.result.current).toMatchObject({ templates: TEMPLATES, failed: false, loading: false })
    expect(getReportTemplatesMock).toHaveBeenCalledTimes(1)
  })

  it('reports a failure and asks again next time', async () => {
    getReportTemplatesMock.mockRejectedValueOnce(new Error('network')).mockResolvedValueOnce(TEMPLATES)
    const failed = renderHook(() => useReportTemplates())
    await waitFor(() => expect(failed.result.current).toMatchObject({ templates: null, failed: true, loading: false }))
    const retried = renderHook(() => useReportTemplates())
    await waitFor(() => expect(retried.result.current.templates).toEqual(TEMPLATES))
  })

  it('asks again on the same page when told to retry', async () => {
    getReportTemplatesMock.mockRejectedValueOnce(new Error('network')).mockResolvedValueOnce(TEMPLATES)
    const { result } = renderHook(() => useReportTemplates())
    await waitFor(() => expect(result.current.failed).toBe(true))
    act(() => result.current.retry())
    await waitFor(() => expect(result.current).toMatchObject({ templates: TEMPLATES, failed: false, loading: false }))
    expect(getReportTemplatesMock).toHaveBeenCalledTimes(2)
  })

  it('reads the list again after a reset', async () => {
    getReportTemplatesMock.mockResolvedValue(TEMPLATES)
    const first = renderHook(() => useReportTemplates())
    await waitFor(() => expect(first.result.current.loading).toBe(false))
    resetReportTemplatesCache()
    const second = renderHook(() => useReportTemplates())
    await waitFor(() => expect(second.result.current.loading).toBe(false))
    expect(getReportTemplatesMock).toHaveBeenCalledTimes(2)
  })
})
