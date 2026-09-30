/** Each card remembers the view it was left in (period, units, filters) until the tab is closed. */
const PREFIX = 'reports.view.'

function storageKey(template: string, report: string): string {
  return `${PREFIX}${template}.${report}`
}

/** The query string a card keeps, without the template's transient parameters (such as an open drill-down). */
export function viewToRemember(search: string, transientParams: readonly string[] = []): string {
  const params = new URLSearchParams(search)
  for (const key of transientParams) params.delete(key)
  const text = params.toString()
  return text ? `?${text}` : ''
}

export function rememberView(
  template: string,
  report: string,
  search: string,
  transientParams: readonly string[] = [],
): void {
  try {
    const value = viewToRemember(search, transientParams)
    if (value) sessionStorage.setItem(storageKey(template, report), value)
    else sessionStorage.removeItem(storageKey(template, report))
  } catch {
    // No session storage (private mode, blocked site data): the card opens with its defaults next time.
  }
}

export function rememberedView(template: string, report: string): string {
  try {
    const value = sessionStorage.getItem(storageKey(template, report)) ?? ''
    return value.startsWith('?') ? value : ''
  } catch {
    return ''
  }
}
