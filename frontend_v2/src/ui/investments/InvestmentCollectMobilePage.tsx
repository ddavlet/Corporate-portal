import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { Alert, Button, Checkbox, Input, Typography, theme } from 'antd'
import { ArrowLeftOutlined, CloseOutlined, RightOutlined } from '@ant-design/icons'

import type { FundingPoolRequestDto } from '../../lib/api'
import { MobileStateWidget } from '../MobileStateWidget'
import { MobileActionsTheme } from '../requests/mobileActionsTheme'
import { Field } from '../requests/MobileFormFieldWidget'
import { RequestStatusToneTag } from '../requests/RequestMobileCardWidget'
import { StepsProgressWidget } from '../requests/StepsProgressWidget'
import { CbuRateAlert } from './CbuRateAlert'
import { FUNDING_METHOD_LABELS, fundingTotalsText, groupByKind, type FundingMethod } from './fundingPool'
import { InvestmentsAccessGateWidget } from './InvestmentsAccessGateWidget'
import { closeToInvestments, INVESTMENTS_PATH } from './investmentsMobileNav'
import { useInvestmentFromRequests } from './useInvestmentFromRequests'
import { asMoney, dateText } from './utils'

/** Step of the wizard, kept in the history entry (`location.state.collectStep`): 0 method, 1 requests, 2 review. */
export type CollectStep = 0 | 1 | 2 | 'done'

const STEP_TITLES = ['Способ внесения', 'Заявки', 'Проверка'] as const

const METHODS: FundingMethod[] = ['cash', 'bank_transfer']

/** History entries the wizard pushes before the review (steps 1 and 2); the result replaces the review's entry. */
const REVIEW_DEPTH = 2

function readStep(state: unknown): CollectStep {
  const step = (state as { collectStep?: unknown } | null)?.collectStep
  return step === 1 || step === 2 || step === 'done' ? step : 0
}

/**
 * `/investments/collect` on a phone: the desktop «Вложение по заявкам» as three steps — the funding method with its
 * counts, the requests as cards (all selected beforehand) with the totals pinned to the bottom, the review with the
 * description and the create button. Every step is a history entry of the same address, so the header's «Назад» and
 * the system «Назад» both lead to the previous step. The result replaces the review entry; going back from it (to an
 * earlier step) leads to `/investments`, and the hook sends nothing twice (useInvestmentFromRequests). Leaving the
 * result goes back past the wizard's entries, so `/investments` is not added to the history again.
 *
 * Only the step lives in the history entry, the method and the selection live in the page: after a reload on step 2
 * or 3 (pull-to-refresh, iOS unloading the PWA) they are lost, so the wizard starts again from the method.
 * Without the «investments» module (a direct link) — «Раздел недоступен», and the pool is not requested.
 */
export function InvestmentCollectMobilePage() {
  return (
    <InvestmentsAccessGateWidget title="Собрать из заявок" testId="investment-collect-mobile">
      <InvestmentCollectWizard />
    </InvestmentsAccessGateWidget>
  )
}

function InvestmentCollectWizard() {
  const { token } = theme.useToken()
  const navigate = useNavigate()
  const location = useLocation()
  // The method was picked on step 1 of this page load: without it steps 2 and 3 have nothing to show.
  const [methodChosen, setMethodChosen] = useState(false)
  const storedStep = readStep(location.state)
  const lostChoice = (storedStep === 1 || storedStep === 2) && !methodChosen
  const step: CollectStep = lostChoice ? 0 : storedStep
  const collect = useInvestmentFromRequests()
  const { pool, created } = collect
  // The history entry the investments were created on: the result replaces it, any other entry means «back».
  const submitKeyRef = useRef<string | null>(null)
  const bodyRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (lostChoice) navigate(location.pathname, { replace: true, state: { collectStep: 0 } })
  }, [lostChoice, location.pathname, navigate])

  useEffect(() => {
    if (created && step !== 'done' && location.key !== submitKeyRef.current) {
      navigate(INVESTMENTS_PATH, { replace: true })
    } else if (!created && step === 'done') {
      // The result entry of an earlier page load: nothing to show, the investments are in the list.
      navigate(INVESTMENTS_PATH, { replace: true })
    }
  }, [created, step, location.key, navigate])

  // Every step starts at its top.
  useEffect(() => {
    if (bodyRef.current) bodyRef.current.scrollTop = 0
  }, [step])

  const goTo = (next: 1 | 2) => navigate(location.pathname, { state: { collectStep: next } })
  // From the result (the review's entry): back past the steps to the page the wizard was opened from.
  const toInvestments = () => closeToInvestments(navigate, REVIEW_DEPTH)

  const submit = async () => {
    submitKeyRef.current = location.key
    const result = await collect.submit()
    if (result) navigate(location.pathname, { replace: true, state: { collectStep: 'done' } })
  }

  const header = (
    <header
      className="m-header"
      style={{ position: 'static', background: token.colorBgContainer, borderBottom: `1px solid ${token.colorBorderSecondary}` }}
    >
      {created ? (
        <Button type="text" className="m-header__button" icon={<CloseOutlined />} aria-label="Закрыть" onClick={toInvestments} />
      ) : step === 0 || step === 'done' ? (
        <Button
          type="text"
          className="m-header__button"
          icon={<CloseOutlined />}
          aria-label="Закрыть"
          onClick={() => closeToInvestments(navigate)}
        />
      ) : (
        <Button type="text" className="m-header__button" icon={<ArrowLeftOutlined />} aria-label="Назад" onClick={() => navigate(-1)} />
      )}
      <h1 className="m-header__title m-ellipsis">Собрать из заявок</h1>
    </header>
  )

  let content: ReactNode
  let footer: ReactNode = null

  if (created) {
    content = (
      <div style={{ display: 'grid', gap: 16 }} data-testid="collect-result">
        <Typography.Title level={5} style={{ margin: 0 }}>
          {`Создано вложений: ${created.map((i) => `№${i.id}`).join(', ')}`}
        </Typography.Title>
        <Typography.Text style={{ color: token.colorTextSecondary }}>
          Вложения отправлены на согласование, если оно настроено.
        </Typography.Text>
        <CbuRateAlert rows={created} />
      </div>
    )
    footer = (
      // Own key: not the «Создать вложение» button in the same place, so its loading state does not carry over.
      <Button key="to-investments" type="primary" block style={{ height: 44 }} onClick={toInvestments}>
        К инвестициям
      </Button>
    )
  } else if (collect.loadError) {
    content = (
      <MobileStateWidget
        state="error"
        title="Не удалось загрузить заявки"
        description={collect.loadError}
        onRetry={collect.reload}
      />
    )
  } else if (!pool) {
    content = <MobileStateWidget state="loading" rows={2} />
  } else if (step === 0 || step === 'done') {
    content = (
      <div role="group" aria-labelledby="collect-method-label" style={{ display: 'grid', gap: 8 }}>
        <Typography.Text id="collect-method-label" strong>
          Как внесены деньги
        </Typography.Text>
        {METHODS.map((m) => (
          <button
            key={m}
            type="button"
            className="m-list-row"
            onClick={() => {
              collect.setMethod(m)
              setMethodChosen(true)
              goTo(1)
            }}
            style={{
              border: `1px solid ${token.colorBorder}`,
              borderRadius: token.borderRadiusLG,
              background: token.colorBgContainer,
            }}
          >
            <span style={{ flex: 1, minWidth: 0, overflowWrap: 'anywhere' }}>
              {`${FUNDING_METHOD_LABELS[m]} (${pool[m].requests.length})`}
            </span>
            <RightOutlined aria-hidden />
          </button>
        ))}
      </div>
    )
  } else if (step === 1) {
    const list = collect.rows
    const renderCards = (rows: FundingPoolRequestDto[]) => (
      <div style={{ display: 'grid', gap: 8 }}>
        {rows.map((r) => (
          <RequestCard key={r.id} row={r} checked={collect.selected.has(r.id)} onToggle={() => collect.toggleOne(r.id)} />
        ))}
      </div>
    )
    if (list.length === 0) {
      content = (
        <MobileStateWidget
          state="empty"
          title="Нет заявок для сбора"
          description={`«${FUNDING_METHOD_LABELS[collect.method]}» — заявок, которые можно собрать во вложение, нет.`}
          action={<Button onClick={() => navigate(-1)}>Выбрать другой способ</Button>}
        />
      )
    } else if (collect.method === 'cash') {
      const groups = groupByKind(list)
      content = (
        <>
          {groups.expense.length > 0 ? (
            <section aria-labelledby="collect-group-expense" style={{ display: 'grid', gap: 8 }}>
              <Typography.Title level={5} id="collect-group-expense" style={{ margin: 0 }}>
                Расходы
              </Typography.Title>
              {renderCards(groups.expense)}
            </section>
          ) : null}
          {groups.transfer.length > 0 ? (
            <section aria-labelledby="collect-group-transfer" style={{ display: 'grid', gap: 8 }}>
              <Typography.Title level={5} id="collect-group-transfer" style={{ margin: 0 }}>
                Перемещения
              </Typography.Title>
              {renderCards(groups.transfer)}
            </section>
          ) : null}
        </>
      )
    } else {
      content = renderCards(list)
    }
    footer = list.length === 0 ? null : (
      <>
        <Typography.Text strong data-testid="collect-totals" aria-live="polite">
          {fundingTotalsText(collect.totals)}
        </Typography.Text>
        <Button type="primary" block style={{ height: 44 }} disabled={collect.chosen.length === 0} onClick={() => goTo(2)}>
          Далее
        </Button>
      </>
    )
  } else {
    content = (
      <>
        {pool.approval_chain_ok === false ? (
          <Alert type="warning" showIcon message="Вложения не будут подтверждаться — не настроено согласование" />
        ) : null}
        <div style={{ display: 'grid', gap: 4 }}>
          <Typography.Text style={{ color: token.colorTextSecondary }}>
            {`${FUNDING_METHOD_LABELS[collect.method]}, выбрано заявок: ${collect.chosen.length}`}
          </Typography.Text>
          <Typography.Text strong data-testid="collect-totals">
            {fundingTotalsText(collect.totals)}
          </Typography.Text>
        </div>
        <Field label="Описание" htmlFor="collect-comment">
          <Input.TextArea
            id="collect-comment"
            autoSize={{ minRows: 3, maxRows: 10 }}
            maxLength={1000}
            value={collect.comment}
            onChange={(e) => collect.setComment(e.target.value)}
          />
        </Field>
      </>
    )
    footer = (
      <Button
        type="primary"
        block
        style={{ height: 44 }}
        loading={collect.submitting}
        disabled={!collect.canSubmit}
        onClick={() => void submit()}
      >
        Создать вложение
      </Button>
    )
  }

  const showSteps = !created && Boolean(pool) && typeof step === 'number'

  return (
    <div className="m-fullscreen m-root" data-testid="investment-collect-mobile" style={{ background: token.colorBgLayout }}>
      {header}
      {showSteps ? <StepsProgressWidget titles={STEP_TITLES} current={Number(step)} /> : null}
      <div ref={bodyRef} className="m-fullscreen__body">
        <div style={{ display: 'grid', gap: 16, padding: 16, minWidth: 0 }}>{content}</div>
      </div>
      {footer ? (
        <MobileActionsTheme>
          <div
            className="m-bottom-bar"
            style={{
              position: 'static',
              flexDirection: 'column',
              background: token.colorBgContainer,
              borderTop: `1px solid ${token.colorBorderSecondary}`,
            }}
          >
            {footer}
          </div>
        </MobileActionsTheme>
      ) : null}
    </div>
  )
}

type RequestCardProps = {
  row: FundingPoolRequestDto
  checked: boolean
  onToggle: () => void
}

/** A request of the pool as a card: the whole card is the checkbox's label. */
function RequestCard({ row, checked, onToggle }: RequestCardProps) {
  const { token } = theme.useToken()
  return (
    <Checkbox
      className="m-check-card"
      checked={checked}
      onChange={onToggle}
      aria-label={`Заявка №${row.id}, ${asMoney(row.amount)} ${row.currency}`}
      style={{
        display: 'flex',
        alignItems: 'center',
        width: '100%',
        margin: 0,
        padding: 12,
        border: `1px solid ${checked ? token.colorPrimary : token.colorBorder}`,
        borderRadius: token.borderRadiusLG,
        background: checked ? token.colorPrimaryBg : token.colorBgContainer,
      }}
    >
      <span style={{ display: 'grid', gap: 2, minWidth: 0, overflowWrap: 'anywhere' }}>
        <span style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
          <Typography.Text strong>{`№${row.id}`}</Typography.Text>
          <Typography.Text style={{ color: token.colorTextSecondary }}>
            {row.submitted_at ? dateText(row.submitted_at) : '—'}
          </Typography.Text>
        </span>
        <Typography.Text>{row.payment_purpose || '—'}</Typography.Text>
        {row.description ? (
          <Typography.Text style={{ color: token.colorTextSecondary }}>{row.description}</Typography.Text>
        ) : null}
        <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
          <Typography.Text strong>{`${asMoney(row.amount)} ${row.currency}`}</Typography.Text>
          {row.is_payed ? (
            <RequestStatusToneTag tone="success">Выплачена</RequestStatusToneTag>
          ) : null}
        </span>
      </span>
    </Checkbox>
  )
}
