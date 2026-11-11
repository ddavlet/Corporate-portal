import { useCallback, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Alert, Button, Card, Select, Space, Tabs, Typography, message } from 'antd'

import {
  DEFAULT_INVESTMENT_FORM_CONFIG,
  getInvestCompanies,
  getInvestmentFormConfig,
  getInvestNotificationConfig,
  getInvestPayoutSchedule,
  getInvestPayoutScheduleShareLinks,
  getInvestReturns,
  getProjectInvestments,
  type InvestCompanyRow,
  type InvestmentFormConfigResponse,
  type InvestPayoutScheduleRow,
  type InvestPayoutScheduleShareLinkRow,
  type InvestReturnRow,
  type ProjectInvestmentRow,
} from '../lib/api'
import { CompaniesTab } from './investments/CompaniesTab'
import { InvestmentsTab } from './investments/InvestmentsTab'
import { InvestmentRecordDetailModal } from './investments/InvestmentRecordDetailModal'
import { ReturnsTab } from './investments/ReturnsTab'
import { ScheduleTab } from './investments/ScheduleTab'
import {
  buildCompanyMap,
  makeCompanyLabel,
  makeCompanyOptions,
  type CompanyFilter,
  type SchedulePaidFilter,
} from './investments/utils'

export function InvestmentsPage() {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [companyFilter, setCompanyFilter] = useState<CompanyFilter>('all')
  const [schedulePaidFilter, setSchedulePaidFilter] = useState<SchedulePaidFilter>('all')
  const [companies, setCompanies] = useState<InvestCompanyRow[]>([])
  const [investments, setInvestments] = useState<ProjectInvestmentRow[]>([])
  const [schedule, setSchedule] = useState<InvestPayoutScheduleRow[]>([])
  const [returns, setReturns] = useState<InvestReturnRow[]>([])
  const [shareLinks, setShareLinks] = useState<InvestPayoutScheduleShareLinkRow[]>([])
  const [invFormCfg, setInvFormCfg] = useState<InvestmentFormConfigResponse | null>(null)
  const [notifyDaysBefore, setNotifyDaysBefore] = useState<number | null>(null)
  // Deep link from notifications: ?tab=<returns|investments|...>&open=<id> opens that tab and the record's card.
  const [searchParams, setSearchParams] = useSearchParams()
  const tabParam = searchParams.get('tab')
  const openParam = Number(searchParams.get('open'))
  const [activeTab, setActiveTab] = useState<string | undefined>(tabParam ?? undefined)

  useEffect(() => {
    if (tabParam) setActiveTab(tabParam)
  }, [tabParam])

  const loadAll = async () => {
    setLoading(true)
    setError(null)
    try {
      const cfgPromise = getInvestmentFormConfig().catch(() => DEFAULT_INVESTMENT_FORM_CONFIG)
      const notifyCfgPromise = getInvestNotificationConfig().catch(() => null)
      const [c, i, s, r, links, cfg, notifyCfg] = await Promise.all([
        getInvestCompanies(),
        getProjectInvestments(),
        getInvestPayoutSchedule(),
        getInvestReturns(),
        getInvestPayoutScheduleShareLinks(),
        cfgPromise,
        notifyCfgPromise,
      ])
      setCompanies(c)
      setInvestments(i)
      setSchedule(s)
      setReturns(r)
      setShareLinks(links)
      setInvFormCfg(cfg)
      setNotifyDaysBefore(notifyCfg?.is_active ? notifyCfg.days_before : null)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Не удалось загрузить данные по инвестициям')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadAll()
  }, [])

  const effectiveFormCfg = invFormCfg ?? DEFAULT_INVESTMENT_FORM_CONFIG

  useEffect(() => {
    if (!effectiveFormCfg.uses_companies) {
      setCompanyFilter('all')
    }
  }, [effectiveFormCfg.uses_companies])

  const companyMap = useMemo(() => buildCompanyMap(companies), [companies])
  const companyLabel = useMemo(() => makeCompanyLabel(companyMap), [companyMap])
  const companyOptions = useMemo(() => makeCompanyOptions(companies), [companies])

  const returnTypeSelectOptions = useMemo(() => {
    const allowed = new Set(effectiveFormCfg.allowed_return_types)
    return effectiveFormCfg.return_type_choices.filter((c) => allowed.has(c.value))
  }, [effectiveFormCfg])

  const tabItems = useMemo(() => {
    const items = []
    if (effectiveFormCfg.uses_companies) {
      items.push({
        key: 'companies',
        label: `Компании (${companies.length})`,
        children: (
          <CompaniesTab loading={loading} companies={companies} onCreated={loadAll} />
        ),
      })
    }
    items.push(
      {
        key: 'investments',
        label: `Заявки на вложение (${investments.length})`,
        children: (
          <InvestmentsTab
            loading={loading}
            rows={investments}
            companies={companies}
            companyLabel={companyLabel}
            companyFilter={companyFilter}
            usesCompanies={effectiveFormCfg.uses_companies}
            onCreated={loadAll}
          />
        ),
      },
      {
        key: 'schedule',
        label: `Расписание (${schedule.length})`,
        children: (
          <ScheduleTab
            loading={loading}
            rows={schedule}
            companies={companies}
            shareLinks={shareLinks}
            companyLabel={companyLabel}
            companyFilter={companyFilter}
            paidFilter={schedulePaidFilter}
            usesCompanies={effectiveFormCfg.uses_companies}
            notifyDaysBefore={notifyDaysBefore}
            onCreated={loadAll}
            onShareLinkCreated={(l) => setShareLinks((prev) => [l, ...prev])}
            onShareLinkDeleted={(id) => setShareLinks((prev) => prev.filter((x) => x.id !== id))}
          />
        ),
      },
      {
        key: 'returns',
        label: `Выплаты (${returns.length})`,
        children: (
          <ReturnsTab
            loading={loading}
            rows={returns}
            companies={companies}
            companyLabel={companyLabel}
            companyFilter={companyFilter}
            usesCompanies={effectiveFormCfg.uses_companies}
            returnTypeSelectOptions={returnTypeSelectOptions}
            onCreated={loadAll}
          />
        ),
      },
    )
    return items
  }, [
    loading,
    companies,
    investments,
    schedule,
    returns,
    shareLinks,
    companyLabel,
    companyFilter,
    schedulePaidFilter,
    effectiveFormCfg.uses_companies,
    returnTypeSelectOptions,
  ])

  const effectiveTab = tabItems.some((t) => t.key === activeTab) ? activeTab : tabItems[0]?.key

  const linkedRecord = useMemo(() => {
    if (!Number.isInteger(openParam) || openParam <= 0) return null
    if (effectiveTab === 'returns') {
      const row = returns.find((r) => r.id === openParam)
      return row ? { kind: 'return' as const, record: row } : null
    }
    if (effectiveTab === 'investments') {
      const row = investments.find((r) => r.id === openParam)
      return row ? { kind: 'project' as const, record: row } : null
    }
    return null
  }, [openParam, effectiveTab, returns, investments])

  const closeLinkedRecord = useCallback(() => {
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        next.delete('open')
        return next
      },
      { replace: true },
    )
  }, [setSearchParams])

  // A deep link to a record that is not in the loaded lists (deleted, another tenant, no access to the module or the
  // load failed) must not fail silently: say so and drop ?open= so the warning does not come back.
  const hasOpenParam = searchParams.has('open')
  useEffect(() => {
    if (loading || !hasOpenParam || linkedRecord) return
    const valid = Number.isInteger(openParam) && openParam > 0
    message.warning(valid ? `Запись #${openParam} не найдена или нет доступа` : 'Запись не найдена или нет доступа')
    closeLinkedRecord()
  }, [loading, hasOpenParam, linkedRecord, openParam, closeLinkedRecord])

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Card>
        <Space style={{ width: '100%', justifyContent: 'space-between' }} wrap>
          <Typography.Title level={4} style={{ margin: 0 }}>
            Инвестиции
          </Typography.Title>
          <Space wrap>
            {effectiveFormCfg.uses_companies ? (
              <Select
                style={{ minWidth: 260 }}
                options={companyOptions}
                value={companyFilter}
                onChange={(v) => setCompanyFilter(v as CompanyFilter)}
              />
            ) : null}
            <Select
              style={{ minWidth: 220 }}
              options={[
                { label: 'Расписание: все', value: 'all' },
                { label: 'Расписание: оплачено', value: 'paid' },
                { label: 'Расписание: не оплачено', value: 'unpaid' },
              ]}
              value={schedulePaidFilter}
              onChange={(v) => setSchedulePaidFilter(v as SchedulePaidFilter)}
            />
            <Button onClick={() => void loadAll()} loading={loading}>
              Обновить
            </Button>
          </Space>
        </Space>
      </Card>

      {error ? <Alert type="error" showIcon message={error} /> : null}

      <Card>
        <Tabs items={tabItems} activeKey={effectiveTab} onChange={setActiveTab} />
      </Card>

      <InvestmentRecordDetailModal
        open={Boolean(linkedRecord)}
        onCancel={closeLinkedRecord}
        kind={linkedRecord?.kind ?? null}
        record={linkedRecord?.record ?? null}
        companyLabel={companyLabel}
        usesCompanies={effectiveFormCfg.uses_companies}
      />
    </Space>
  )
}
