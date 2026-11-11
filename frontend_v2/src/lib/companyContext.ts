import { LIST_PAGE_SESSION_PREFIX } from './useListPageSession'
import { REPORT_VIEW_PREFIX } from '../ui/reports/reportViewMemory'
import { resetTenantAdminCache } from './useTenantAdmin'
import { resetReportTemplatesCache } from './useReportTemplates'
import { resetActionItemsCache } from './useActionItems'
import { isSharedAppMode } from './portalMode'

/**
 * Company of the shared app host (see portalMode.ts). Each browser tab keeps its own company in sessionStorage, so two
 * tabs can work in two companies at once; the last pick is also the default for new tabs (localStorage).
 */

export const TAB_COMPANY_KEY = 'kolberg_v2_company'
export const DEFAULT_COMPANY_KEY = 'kolberg_v2_company_default'

const COMPANY_SCOPED_SESSION_PREFIXES = [LIST_PAGE_SESSION_PREFIX, REPORT_VIEW_PREFIX]

function readStorage(storage: () => Storage, key: string): string | null {
  try {
    const value = storage().getItem(key)?.trim()
    return value || null
  } catch {
    return null
  }
}

/** Subdomain of the company this tab works in, or null when none is picked yet. */
export function getTabCompany(): string | null {
  return readStorage(() => sessionStorage, TAB_COMPANY_KEY)
}

/** The company picked last on this device: the starting choice for a new tab. */
export function getDefaultCompany(): string | null {
  return readStorage(() => localStorage, DEFAULT_COMPANY_KEY)
}

/**
 * Sets the company of this tab only, keeping the device default (a deep link of another company opens it here but
 * does not change where new tabs start).
 */
export function setTabCompanyOnly(subdomain: string): void {
  try {
    sessionStorage.setItem(TAB_COMPANY_KEY, subdomain)
  } catch {
    // No session storage: requests go without X-Tenant and the server answers tenant_required.
  }
}

/** Sets the company of this tab and makes it the device default (an explicit pick in the switcher). */
export function setTabCompany(subdomain: string): void {
  setTabCompanyOnly(subdomain)
  try {
    localStorage.setItem(DEFAULT_COMPANY_KEY, subdomain)
  } catch {
    // The default is a convenience only.
  }
}

/** Forgets this tab's company (logout); the device default stays for the next sign-in. */
export function clearTabCompany(): void {
  try {
    sessionStorage.removeItem(TAB_COMPANY_KEY)
  } catch {
    // Nothing to clear.
  }
}

/**
 * Drops everything the previous company left in memory and in this tab's sessionStorage: module caches (admin flag,
 * report templates, action items) and the saved state of list feeds and report cards. Other keys stay.
 *
 * On the shared app host the action items store holds all the user's companies, so a switch keeps it (logout resets it).
 */
export function resetCompanyScopedState(): void {
  resetTenantAdminCache()
  resetReportTemplatesCache()
  if (!isSharedAppMode()) resetActionItemsCache()
  try {
    const keys: string[] = []
    for (let i = 0; i < sessionStorage.length; i += 1) {
      const key = sessionStorage.key(i)
      if (key && COMPANY_SCOPED_SESSION_PREFIXES.some((prefix) => key.startsWith(prefix))) keys.push(key)
    }
    keys.forEach((key) => sessionStorage.removeItem(key))
  } catch {
    // No session storage: nothing was saved either.
  }
}
