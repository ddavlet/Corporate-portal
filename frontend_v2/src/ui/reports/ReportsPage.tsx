import { Alert, Segmented, Skeleton } from 'antd'
import { lazy, Suspense, useEffect, useMemo, useState, type ComponentType, type LazyExoticComponent } from 'react'
import { useSearchParams } from 'react-router-dom'
import { getReportTemplates, type ReportKind, type ReportTemplatesResponse } from '../../lib/reportsApi'
import { useUserPreference } from '../../lib/useUserPreference'
import { FALLBACK_TEMPLATE, resolveReportTemplate } from './resolveReportTemplate'
import { REPORT_TEMPLATE_REGISTRY } from './templates/registry'
import type { ReportTemplateProps } from './templates/types'

const TEMPLATE_PREFERENCE_KEY = 'reports.template.v1'

/** One lazy component per template, created once, so switching back does not remount or reload it. */
const lazyTemplates = new Map<string, LazyExoticComponent<ComponentType<ReportTemplateProps>>>()

function templateComponent(key: string): LazyExoticComponent<ComponentType<ReportTemplateProps>> {
  const definition = REPORT_TEMPLATE_REGISTRY[key] ?? REPORT_TEMPLATE_REGISTRY[FALLBACK_TEMPLATE]
  let component = lazyTemplates.get(definition.key)
  if (!component) {
    component = lazy(definition.load)
    lazyTemplates.set(definition.key, component)
  }
  return component
}

export function ReportsPage() {
  const [params, setParams] = useSearchParams()
  const [templates, setTemplates] = useState<ReportTemplatesResponse | null>(null)
  const [failed, setFailed] = useState(false)
  // '' = no choice yet; the preferences API rejects null, and the hook saves the loaded value back.
  const preference = useUserPreference<string>({
    key: TEMPLATE_PREFERENCE_KEY,
    defaultValue: '',
    normalize: (raw) => (typeof raw === 'string' ? raw : ''),
  })

  useEffect(() => {
    let active = true
    getReportTemplates()
      .then((data) => {
        if (active) setTemplates(data)
      })
      .catch(() => {
        if (active) setFailed(true)
      })
    return () => {
      active = false
    }
  }, [])

  const allowed = useMemo(() => {
    const keys = templates && !failed ? templates.allowed.map((template) => template.key) : [FALLBACK_TEMPLATE]
    return keys.filter((key) => key in REPORT_TEMPLATE_REGISTRY)
  }, [templates, failed])

  const labels = useMemo(() => {
    const out: Record<string, string> = {}
    for (const [key, definition] of Object.entries(REPORT_TEMPLATE_REGISTRY)) out[key] = definition.label
    for (const template of templates?.available ?? []) out[template.key] = template.label
    return out
  }, [templates])

  const supports = useMemo(
    () => Object.fromEntries(Object.entries(REPORT_TEMPLATE_REGISTRY).map(([key, definition]) => [key, definition.supports])),
    [],
  )

  if ((!templates && !failed) || preference.isLoading) return <Skeleton active />

  const report: ReportKind = params.get('r') === 'cashflow' ? 'cashflow' : 'pnl'
  const resolution = resolveReportTemplate({
    requested: params.get('t'),
    preferred: preference.value || null,
    tenantDefault: templates && !failed ? templates.default : FALLBACK_TEMPLATE,
    allowed,
    supports,
    report,
    labels,
  })
  const Template = templateComponent(resolution.key)

  const choose = (key: string) => {
    preference.setValue(key)
    setParams(
      (previous) => {
        const next = new URLSearchParams(previous)
        next.set('t', key)
        return next
      },
      { replace: true },
    )
  }

  const switcher =
    allowed.length > 1 ? (
      <Segmented
        aria-label="Шаблон отчёта"
        value={resolution.key}
        onChange={(value) => choose(String(value))}
        options={allowed.map((key) => ({ label: labels[key] ?? key, value: key }))}
      />
    ) : null

  return (
    <>
      {resolution.notice ? <Alert type="info" showIcon message={resolution.notice} style={{ marginBottom: 12 }} /> : null}
      <Suspense fallback={<Skeleton active />}>
        <Template templateSwitcher={switcher} />
      </Suspense>
    </>
  )
}
