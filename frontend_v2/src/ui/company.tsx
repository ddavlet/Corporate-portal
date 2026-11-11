import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { Button, Result, Space, Spin } from 'antd'
import { LogoutOutlined } from '@ant-design/icons'
import { isSharedAppMode } from '../lib/portalMode'
import { setTenantAccessLostHandler } from '../lib/api'
import { notifyInfo } from '../lib/apiNotify'
import {
  clearTabCompany,
  getDefaultCompany,
  getTabCompany,
  resetCompanyScopedState,
  setTabCompany,
  setTabCompanyOnly,
} from '../lib/companyContext'
import { getMyCompanies, type MyCompany } from '../lib/myCompaniesApi'
import { useAuth } from './auth'
import { NoCompaniesPage } from './NoCompaniesPage'

/** Query parameter of deep links on the shared app host: `/app/requests/12?company=acme`. */
export const COMPANY_PARAM = 'company'

/** Where the portal opens after a company switch. */
const AFTER_SWITCH_PATH = '/requests'

export type CompanyContextValue = {
  /** True on the shared app host: the company comes from the switcher, not from the subdomain. */
  enabled: boolean
  companies: MyCompany[]
  /** Subdomain of the company of this tab (null on a tenant subdomain). */
  current: string | null
  currentCompany: MyCompany | null
  /** Clears company-scoped caches and saved list/report state, then opens the start page in `subdomain`. */
  switchCompany: (subdomain: string) => void
}

const SUBDOMAIN_MODE: CompanyContextValue = {
  enabled: false,
  companies: [],
  current: null,
  currentCompany: null,
  switchCompany: () => undefined,
}

const CompanyContext = createContext<CompanyContextValue>(SUBDOMAIN_MODE)

export function useCompany(): CompanyContextValue {
  return useContext(CompanyContext)
}

/** This tab's company if it is still in the list, else the device default, else the first by name. */
export function pickCompany(companies: MyCompany[], tab: string | null, fallback: string | null): string | null {
  const has = (subdomain: string | null) => Boolean(subdomain) && companies.some((c) => c.subdomain === subdomain)
  if (has(tab)) return tab
  if (has(fallback)) return fallback
  const sorted = [...companies].sort((a, b) => a.name.localeCompare(b.name, 'ru'))
  return sorted[0]?.subdomain ?? null
}

function CenteredSpin() {
  return (
    <div className="login-page" role="status" aria-label="Загрузка компании">
      <Spin size="large" />
    </div>
  )
}

type LoadState =
  | { status: 'loading' }
  | { status: 'error' }
  | { status: 'ready'; companies: MyCompany[] }

function SharedCompanyProvider({ children }: { children: ReactNode }) {
  const location = useLocation()
  const navigate = useNavigate()
  const { logout } = useAuth()
  const [load, setLoad] = useState<LoadState>({ status: 'loading' })
  const [attempt, setAttempt] = useState(0)
  const [current, setCurrent] = useState<string | null>(null)
  /** A switch in progress: the old tree is unmounted first, so its cleanups cannot write into the new company. */
  const [pending, setPending] = useState<string | null>(null)
  const currentRef = useRef<string | null>(null)
  /** The company list is being read again because the server refused this tab's company. */
  const recoveringRef = useRef(false)
  /** The company the last recovery left; a second refusal for it is not recovered again (no reload loop). */
  const lostRef = useRef<string | null>(null)

  useEffect(() => {
    currentRef.current = current
  }, [current])

  const companyParam = new URLSearchParams(location.search).get(COMPANY_PARAM)?.trim().toLowerCase() || null
  const companies = load.status === 'ready' ? load.companies : []
  const paramIsMine = Boolean(companyParam) && companies.some((c) => c.subdomain === companyParam)

  useEffect(() => {
    let cancelled = false
    setLoad({ status: 'loading' })
    getMyCompanies()
      .then((list) => {
        if (cancelled) return
        const picked = pickCompany(list, getTabCompany(), getDefaultCompany())
        if (picked) setTabCompany(picked)
        setCurrent(picked)
        setLoad({ status: 'ready', companies: list })
        if (recoveringRef.current) {
          recoveringRef.current = false
          const lost = lostRef.current
          if (picked && picked !== lost) {
            const name = list.find((c) => c.subdomain === picked)?.name ?? picked
            notifyInfo(`Нет доступа к прежней компании. Открыта компания «${name}».`)
            navigate(AFTER_SWITCH_PATH, { replace: true })
          }
        }
      })
      .catch(() => {
        recoveringRef.current = false
        if (!cancelled) setLoad({ status: 'error' })
      })
    return () => {
      cancelled = true
    }
    // Only a new attempt reads the list again (navigate may change identity on every location change).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [attempt])

  // The server refused this tab's company (membership or company switched off while the tab was open): read the list
  // again and pick an available company, or show «Нет доступных компаний».
  useEffect(() => {
    setTenantAccessLostHandler((code, sentTenant) => {
      if (recoveringRef.current) return true
      const tab = currentRef.current
      if (!tab) return false
      // A late answer for the previous company after a switch: nothing to recover.
      if (sentTenant && sentTenant !== tab) return true
      if (lostRef.current === tab) return false
      if (code === 'tenant_required') {
        // The header went missing (tab storage cleared): put the company back; without session storage keep the toast.
        setTabCompanyOnly(tab)
        if (getTabCompany() !== tab) return false
      } else {
        clearTabCompany()
      }
      lostRef.current = tab
      recoveringRef.current = true
      resetCompanyScopedState()
      setAttempt((n) => n + 1)
      return true
    })
    return () => setTenantAccessLostHandler(null)
  }, [])

  // Deep link of one of my companies: switch to it (if needed) and drop the parameter from the address.
  useEffect(() => {
    if (load.status !== 'ready' || !companyParam || !paramIsMine) return
    if (companyParam !== current) {
      resetCompanyScopedState()
      // A link opens its company in this tab only: new tabs keep starting in the company picked in the switcher.
      setTabCompanyOnly(companyParam)
      setCurrent(companyParam)
      const name = companies.find((c) => c.subdomain === companyParam)?.name ?? companyParam
      notifyInfo(`Вы перешли в компанию «${name}».`)
    }
    const params = new URLSearchParams(location.search)
    params.delete(COMPANY_PARAM)
    const search = params.toString()
    navigate({ pathname: location.pathname, search: search ? `?${search}` : '', hash: location.hash }, { replace: true })
  }, [load.status, companyParam, paramIsMine, current, companies, location.pathname, location.search, location.hash, navigate])

  useEffect(() => {
    if (!pending) return
    resetCompanyScopedState()
    setTabCompany(pending)
    setCurrent(pending)
    setPending(null)
    lostRef.current = null
    // Replace: «Back» must not open an address of the previous company inside the new one.
    navigate(AFTER_SWITCH_PATH, { replace: true })
  }, [pending, navigate])

  const switchCompany = useCallback(
    (subdomain: string) => {
      if (subdomain === current) return
      if (!companies.some((c) => c.subdomain === subdomain)) return
      setPending(subdomain)
    },
    [companies, current],
  )

  const value = useMemo<CompanyContextValue>(
    () => ({
      enabled: true,
      companies,
      current,
      currentCompany: companies.find((c) => c.subdomain === current) ?? null,
      switchCompany,
    }),
    [companies, current, switchCompany],
  )

  const signOut = () => {
    logout()
    navigate('/login', { replace: true })
  }

  if (load.status === 'loading') return <CenteredSpin />
  if (load.status === 'error') {
    return (
      <div className="login-page">
        <Result
          status="error"
          title="Не удалось загрузить список компаний"
          subTitle="Проверьте соединение и попробуйте ещё раз."
          extra={
            <Space wrap>
              <Button type="primary" onClick={() => setAttempt((n) => n + 1)}>
                Повторить
              </Button>
              <Button icon={<LogoutOutlined />} onClick={signOut}>
                Выйти
              </Button>
            </Space>
          }
        />
      </div>
    )
  }
  if (companies.length === 0) return <NoCompaniesPage />
  if (companyParam && !paramIsMine) {
    // Nothing below is mounted, so nothing is requested for a company the user is not a member of.
    return (
      <div className="login-page">
        <Result
          status="403"
          title="Нет доступа к компании"
          subTitle="Ссылка ведёт в компанию, где у вас нет доступа. Текущая компания не изменилась."
          extra={
            <Button type="primary" onClick={() => navigate(AFTER_SWITCH_PATH, { replace: true })}>
              Перейти к заявкам
            </Button>
          }
        />
      </div>
    )
  }
  if (companyParam || pending || !current) return <CenteredSpin />

  return <CompanyContext.Provider value={value}>{children}</CompanyContext.Provider>
}

/**
 * Company of the shared app host. On a tenant subdomain (and in the Mini App) it renders only its children and asks
 * nothing; useCompany() then reports `enabled: false`.
 */
export function CompanyProvider({ children }: { children: ReactNode }) {
  if (!isSharedAppMode()) return <>{children}</>
  return <SharedCompanyProvider>{children}</SharedCompanyProvider>
}
