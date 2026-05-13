import { useEffect, useMemo, useState } from 'react'
import { Alert, Button, Card, Select, Space, Tabs, Typography } from 'antd'

import {
  DEFAULT_INVESTMENT_FORM_CONFIG,
  getInvestCompanies,
  getInvestmentFormConfig,
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

  const loadAll = async () => {
    setLoading(true)
    setError(null)
    try {
      const cfgPromise = getInvestmentFormConfig().catch(() => DEFAULT_INVESTMENT_FORM_CONFIG)
      const [c, i, s, r, links, cfg] = await Promise.all([
        getInvestCompanies(),
        getProjectInvestments(),
        getInvestPayoutSchedule(),
        getInvestReturns(),
        getInvestPayoutScheduleShareLinks(),
        cfgPromise,
      ])
      setCompanies(c)
      setInvestments(i)
      setSchedule(s)
      setReturns(r)
      setShareLinks(links)
      setInvFormCfg(cfg)
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
        label: `Вложения (${investments.length})`,
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
        <Tabs items={tabItems} />
      </Card>
    </Space>
  )
}
