import dayjs from 'dayjs'

const YEAR_RE = /^\d{4}$/
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/

/** `y` in a Classic link: a year from 2000 to 2100; anything else means the current year (null). */
export function yearFromParam(raw: string | null): number | null {
  if (!raw || !YEAR_RE.test(raw)) return null
  const year = Number(raw)
  return year >= 2000 && year <= 2100 ? year : null
}

/** `from` / `to` in a Classic link: a real calendar date; anything else means no bound (null). */
export function dateFromParam(raw: string | null): string | null {
  return raw && DATE_RE.test(raw) && dayjs(raw).format('YYYY-MM-DD') === raw ? raw : null
}
