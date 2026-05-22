import React, { createContext, useContext, useEffect, useMemo, useState } from 'react'
import { getModuleCatalog, type ModuleCatalogRow } from '../lib/api'

type ModuleAccessContextValue = {
  loading: boolean
  hasAccess: (moduleKey: string) => boolean
}

const ModuleAccessContext = createContext<ModuleAccessContextValue | null>(null)

export function ModuleAccessProvider({ children }: { children: React.ReactNode }) {
  const [loading, setLoading] = useState(true)
  const [rows, setRows] = useState<ModuleCatalogRow[] | null>(null)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setLoading(true)
      try {
        const data = await getModuleCatalog()
        if (!cancelled) setRows(data)
      } catch {
        if (!cancelled) setRows(null)
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const value = useMemo<ModuleAccessContextValue>(() => {
    const allowed = new Set((rows || []).filter((r) => r.effective_enabled).map((r) => r.module_key))
    return {
      loading,
      hasAccess: (moduleKey: string) => {
        if (!rows) return false
        return allowed.has(moduleKey)
      },
    }
  }, [loading, rows])

  return <ModuleAccessContext.Provider value={value}>{children}</ModuleAccessContext.Provider>
}

export function useModuleAccess() {
  const ctx = useContext(ModuleAccessContext)
  if (!ctx) throw new Error('useModuleAccess must be used within ModuleAccessProvider')
  return ctx
}
