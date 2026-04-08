import dayjs, { type Dayjs } from 'dayjs'

export const TASHKENT_TZ = 'Asia/Tashkent'

export function nowTashkent(): Dayjs {
  return dayjs().tz(TASHKENT_TZ)
}

export function monthStartTashkent(input?: Dayjs | string | null): Dayjs {
  if (!input) return nowTashkent().startOf('month')
  if (typeof input === 'string') return dayjs(input).tz(TASHKENT_TZ).startOf('month')
  return input.tz(TASHKENT_TZ).startOf('month')
}
