import { describe, expect, it } from 'vitest'
import { dateFromParam, yearFromParam } from './classicUrlState'

describe('classic link values', () => {
  it('reads a year and ignores anything else', () => {
    expect(yearFromParam('2025')).toBe(2025)
    for (const raw of [null, '', 'abc', '1800', '2101', '2025.5', ' 2025']) expect(yearFromParam(raw)).toBeNull()
  })

  it('reads a calendar date and ignores anything else', () => {
    expect(dateFromParam('2026-08-01')).toBe('2026-08-01')
    for (const raw of [null, '', '2026-13-45', '2026-02-30', '01.08.2026', '2026-8-1']) expect(dateFromParam(raw)).toBeNull()
  })
})
