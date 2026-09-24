import { describe, expect, it } from 'vitest'
import { ApiError } from './api'
import { describeReportError, NETWORK_ERROR_MESSAGE } from './reportErrors'

describe('describeReportError', () => {
  it('keeps the server message', () => {
    expect(describeReportError(new ApiError(503, 'Отчёт не настроен'), 'fallback')).toBe('Отчёт не настроен')
  })

  it('explains a lost connection in Russian instead of the browser text', () => {
    expect(describeReportError(new TypeError('Failed to fetch'), 'fallback')).toBe(NETWORK_ERROR_MESSAGE)
    expect(describeReportError(new TypeError('Load failed'), 'fallback')).toBe(NETWORK_ERROR_MESSAGE)
  })

  it('falls back for anything else', () => {
    expect(describeReportError(new Error('boom'), 'Не удалось выгрузить Excel')).toBe('Не удалось выгрузить Excel')
    expect(describeReportError('weird', 'Не удалось выгрузить Excel')).toBe('Не удалось выгрузить Excel')
  })
})
