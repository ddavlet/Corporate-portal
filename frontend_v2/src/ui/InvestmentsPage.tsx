import { useEffect, useMemo, useState } from 'react'
import { Alert, Button, Card, Select, Space, Tabs, Typography } from 'antd'

import {
  getInvestCompanies,
  getInvestPayoutSchedule,
  getInvestPayoutScheduleShareLinks,
  getInvestReturns,
  getProjectInvestments,
  type InvestCompanyRow,
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

  const loadAll = async () => {
    setLoading(true)
    setError(null)
    try {
      const [c, i, s, r, links] = await Promise.all([
        getInvestCompanies(),
        getProjectInvestments(),
        getInvestPayoutSchedule(),
        getInvestReturns(),
        getInvestPayoutScheduleShareLinks(),
      ])
      setCompanies(c)
      setInvestments(i)
      setSchedule(s)
      setReturns(r)
      setShareLinks(links)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Не удалось загрузить данные по инвестициям')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadAll()
  }, [])

  const companyMap = useMemo(() => buildCompanyMap(companies), [companies])
  const companyLabel = useMemo(() => makeCompanyLabel(companyMap), [companyMap])
  const companyOptions = useMemo(() => makeCompanyOptions(companies), [companies])

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Card>
        <Space style={{ width: '100%', justifyContent: 'space-between' }} wrap>
          <Typography.Title level={4} style={{ margin: 0 }}>
            Инвестиции
          </Typography.Title>
          <Space wrap>
            <Select
              style={{ minWidth: 260 }}
              options={companyOptions}
              value={companyFilter}
              onChange={(v) => setCompanyFilter(v as CompanyFilter)}
            />
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
        <Tabs
          items={[
            {
              key: 'companies',
              label: `Компании (${companies.length})`,
              children: (
                <CompaniesTab loading={loading} companies={companies} onCreated={loadAll} />
              ),
            },
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
                  onCreated={loadAll}
                />
              ),
            },
          ]}
        />
      </Card>
    </Space>
  )
}
