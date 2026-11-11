import { useEffect, useMemo, useState } from 'react'
import { Alert, Button, Checkbox, Form, Input, Segmented, Skeleton, Tag, Typography, message } from 'antd'
import { useNavigate } from 'react-router-dom'
import { ArrowLeftOutlined } from '@ant-design/icons'

import {
  createInvestmentsFromRequests,
  getFundingPool,
  type FundingPoolDto,
  type FundingPoolRequestDto,
} from '../../lib/api'
import {
  FUNDING_METHOD_LABELS,
  defaultCollectComment,
  groupByKind,
  totalsByCurrency,
  type CurrencyTotal,
  type FundingMethod,
} from '../investments/fundingPool'
import { asMoney, dateText } from '../investments/utils'
import { tgHaptic } from './tgHaptic'
import { useTgMainButton } from './useTgMainButton'

function totalLine(total: CurrencyTotal): string {
  const n = total.count
  const word =
    n % 10 === 1 && n % 100 !== 11
      ? 'заявка'
      : n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 10 || n % 100 >= 20)
        ? 'заявки'
        : 'заявок'
  return `${asMoney(total.amount)} ${total.currency} (${n} ${word})`
}

/**
 * `/tg/investments/projects/collect` — вложение по заявкам на расход (инвестиционный режим).
 * Мобильный аналог портального `InvestmentFromRequestsModal`: тот же пул и тот же endpoint.
 */
export function TgInvestmentsCollectPage() {
  const navigate = useNavigate()
  const [pool, setPool] = useState<FundingPoolDto | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [method, setMethod] = useState<FundingMethod>('cash')
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [editedComment, setEditedComment] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const data = await getFundingPool()
        if (cancelled) return
        setPool(data)
        setSelected(new Set([...data.cash.requests, ...data.bank_transfer.requests].map((r) => r.id)))
      } catch (e: unknown) {
        if (!cancelled) setLoadError(e instanceof Error ? e.message : 'Не удалось загрузить заявки')
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const rows = useMemo(() => (pool ? pool[method].requests : []), [pool, method])
  const chosen = useMemo(() => rows.filter((r) => selected.has(r.id)), [rows, selected])
  const totals = useMemo(() => totalsByCurrency(rows, selected), [rows, selected])
  const generated = useMemo(() => defaultCollectComment(chosen), [chosen])
  const comment = editedComment ?? generated

  const canSubmit = Boolean(pool) && chosen.length > 0

  const toggle = (id: number, checked: boolean) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (checked) next.add(id)
      else next.delete(id)
      return next
    })
  }

  async function submit() {
    if (!canSubmit || submitting) return
    setSubmitting(true)
    setSubmitError(null)
    try {
      const created = await createInvestmentsFromRequests({
        funding_method: method,
        request_ids: chosen.map((r) => r.id),
        // Текст по умолчанию — только превью: пустой comment бэкенд заменит описанием на каждую валюту.
        comment: editedComment ?? '',
      })
      message.success(`Создано вложений: ${created.investments.map((i) => `№${i.id}`).join(', ')}`)
      navigate('/tg/investments/projects', { replace: true })
    } catch (e: unknown) {
      setSubmitError(e instanceof Error ? e.message : 'Не удалось создать вложение')
    } finally {
      setSubmitting(false)
    }
  }

  useTgMainButton({
    text: 'Создать вложение',
    onClick: () => void submit(),
    loading: submitting,
    disabled: !canSubmit,
  })

  const renderRow = (r: FundingPoolRequestDto) => (
    <label key={r.id} className="tg-request-row" style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
      <Checkbox
        checked={selected.has(r.id)}
        onChange={(e) => toggle(r.id, e.target.checked)}
        aria-label={`Заявка №${r.id}`}
        style={{ marginTop: 2 }}
      />
      <span style={{ flex: 1, minWidth: 0 }}>
        <span className="tg-request-row-title" style={{ display: 'block' }}>
          №{r.id} · {r.description || r.payment_purpose || '—'}
        </span>
        <span className="tg-request-row-meta">
          <span className="tg-request-row-amount">
            {asMoney(r.amount)} {r.currency}
          </span>
          {r.submitted_at ? <span>{dateText(r.submitted_at)}</span> : null}
          {r.payment_purpose && r.description ? <span>{r.payment_purpose}</span> : null}
          {r.is_payed ? (
            <Tag color="success" style={{ margin: 0 }}>
              Выплачена
            </Tag>
          ) : null}
        </span>
      </span>
    </label>
  )

  const renderGroup = (title: string | null, list: FundingPoolRequestDto[]) =>
    list.length === 0 ? null : (
      <div style={{ marginBottom: 12 }}>
        {title ? (
          <Typography.Text strong style={{ display: 'block', marginBottom: 8 }}>
            {title}
          </Typography.Text>
        ) : null}
        {list.map(renderRow)}
      </div>
    )

  const renderList = () => {
    if (rows.length === 0) {
      return (
        <Typography.Paragraph type="secondary" style={{ textAlign: 'center', padding: '24px 8px' }}>
          Нет заявок для сбора.
        </Typography.Paragraph>
      )
    }
    if (method === 'bank_transfer') return renderGroup(null, rows)
    const groups = groupByKind(rows)
    return (
      <>
        {renderGroup('Расходы', groups.expense)}
        {renderGroup('Перемещения', groups.transfer)}
      </>
    )
  }

  return (
    <div className="tg-investments-page" style={{ paddingBottom: 88 }}>
      <Button
        icon={<ArrowLeftOutlined />}
        size="large"
        onClick={() => {
          tgHaptic.tap()
          navigate('/tg/investments/projects')
        }}
        style={{ marginBottom: 12, borderRadius: 12 }}
      >
        Назад
      </Button>

      <Typography.Title level={4} style={{ margin: '0 0 16px', fontWeight: 700 }}>
        Вложение по заявкам
      </Typography.Title>

      {loadError ? <Alert type="error" showIcon message={loadError} style={{ marginBottom: 12, borderRadius: 12 }} /> : null}
      {!pool && !loadError ? <Skeleton active paragraph={{ rows: 6 }} /> : null}

      {pool ? (
        <>
          {!pool.approval_chain_ok ? (
            <Alert
              type="warning"
              showIcon
              message="Вложения не будут подтверждаться — не настроено согласование"
              style={{ marginBottom: 12, borderRadius: 12 }}
            />
          ) : null}

          <Segmented
            block
            size="large"
            value={method}
            onChange={(v) => {
              setMethod(v as FundingMethod)
              setEditedComment(null)
            }}
            options={[
              { value: 'cash', label: `${FUNDING_METHOD_LABELS.cash} (${pool.cash.requests.length})` },
              {
                value: 'bank_transfer',
                label: `Переводом (${pool.bank_transfer.requests.length})`,
              },
            ]}
            style={{ marginBottom: 16 }}
          />

          {renderList()}

          <Typography.Text strong style={{ display: 'block', margin: '8px 0 16px' }}>
            {totals.length === 0 ? 'Итого: ничего не выбрано' : `Итого: ${totals.map(totalLine).join('; ')}`}
          </Typography.Text>

          <Form layout="vertical">
            <Form.Item label="Описание">
              <Input.TextArea
                rows={3}
                maxLength={1000}
                value={comment}
                onChange={(e) => setEditedComment(e.target.value)}
              />
            </Form.Item>
          </Form>
        </>
      ) : null}

      {submitError ? (
        <Alert type="error" showIcon message={submitError} style={{ marginBottom: 12, borderRadius: 12 }} />
      ) : null}
    </div>
  )
}
