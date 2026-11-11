import { useCallback, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Alert, Button, Card, Select, Space, Tabs, Typography, message } from 'antd'

import {
  DEFAULT_INVESTMENT_FORM_CONFIG,
  getInvestmentFormConfig,
  getInvestNotificationConfig,
  getInvestPayoutSchedule,
  getInvestPayoutScheduleShareLinks,
  getInvestReturns,
  getProjectInvestments,
  type InvestmentFormConfigResponse,
  type InvestPayoutScheduleRow,
  type InvestPayoutScheduleShareLinkRow,
  type InvestReturnRow,
  type ProjectInvestmentRow,
} from '../lib/api'
import { InvestmentsTab } from './investments/InvestmentsTab'
import { InvestmentRecordDetailModal } from './investments/InvestmentRecordDetailModal'
import { ReturnsTab } from './investments/ReturnsTab'
import { ScheduleTab } from './investments/ScheduleTab'
import { type SchedulePaidFilter } from './investments/utils'

export function InvestmentsPage() {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [schedulePaidFilter, setSchedulePaidFilter] = useState<SchedulePaidFilter>('all')
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
      const [i, s, r, links, cfg, notifyCfg] = await Promise.all([
        getProjectInvestments(),
        getInvestPayoutSchedule(),
        getInvestReturns(),
        getInvestPayoutScheduleShareLinks(),
        cfgPromise,
        notifyCfgPromise,
      ])
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

  const returnTypeSelectOptions = useMemo(() => {
    const allowed = new Set(effectiveFormCfg.allowed_return_types)
    return effectiveFormCfg.return_type_choices.filter((c) => allowed.has(c.value))
  }, [effectiveFormCfg])

  const tabItems = useMemo(
    () => [
      {
        key: 'investments',
        label: `Заявки на вложение (${investments.length})`,
        children: (
          <InvestmentsTab
            loading={loading}
            rows={investments}
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
            shareLinks={shareLinks}
            paidFilter={schedulePaidFilter}
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
            returnTypeSelectOptions={returnTypeSelectOptions}
            onCreated={loadAll}
          />
        ),
      },
    ],
    [loading, investments, schedule, returns, shareLinks, schedulePaidFilter, returnTypeSelectOptions],
  )

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
      />
    </Space>
  )
}
