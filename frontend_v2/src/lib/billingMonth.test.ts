import dayjs from 'dayjs'
import timezone from 'dayjs/plugin/timezone'
import utc from 'dayjs/plugin/utc'
import { describe, expect, it } from 'vitest'

import { formatBillingMonth } from './billingMonth'
import { monthStartTashkent } from './tashkentTime'

dayjs.extend(utc)
dayjs.extend(timezone)

describe('formatBillingMonth', () => {
  it('shows the month in Russian even after conversion to Tashkent time', () => {
    const month = monthStartTashkent(dayjs('2026-11-15T12:00:00Z'))
    expect(formatBillingMonth(month)).toBe('ноябрь 2026')
  })

  it('does not change the locale of the value it formats', () => {
    const month = monthStartTashkent(dayjs('2026-01-10T12:00:00Z'))
    const before = month.locale()
    expect(formatBillingMonth(month)).toBe('январь 2026')
    expect(month.locale()).toBe(before)
  })
})
