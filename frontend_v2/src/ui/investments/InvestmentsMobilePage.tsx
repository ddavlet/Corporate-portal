import { useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Button, Typography, message, theme } from 'antd'
import { FileAddOutlined, MergeCellsOutlined, PlusOutlined } from '@ant-design/icons'

import { getInvestReturns, getProjectInvestments, type InvestReturnRow, type ProjectInvestmentRow } from '../../lib/api'
import { useInvestmentFundingModeStatus } from '../../lib/useInvestmentFundingModeStatus'
import { MobileStateWidget } from '../MobileStateWidget'
import { useMobileHeader } from '../mobileShell'
import { useModuleAccess } from '../moduleAccess'
import { MobileActionsTheme } from '../requests/mobileActionsTheme'
import { InvestmentRecordDetailModal } from './InvestmentRecordDetailModal'
import { INVEST_RETURN_NEW_PATH, INVESTMENT_COLLECT_PATH, INVESTMENT_NEW_PATH } from './investmentsMobileNav'

type LinkedRecord =
  | { kind: 'return'; record: InvestReturnRow }
  | { kind: 'project'; record: ProjectInvestmentRow }

/** A record of a notification's link `?tab=<returns|investments>&open=<id>`; null when it is not there. */
async function findLinkedRecord(tab: string, id: number): Promise<LinkedRecord | null> {
  if (tab === 'returns') {
    const row = (await getInvestReturns()).find((r) => r.id === id)
    return row ? { kind: 'return', record: row } : null
  }
  const row = (await getProjectInvestments()).find((r) => r.id === id)
  return row ? { kind: 'project', record: row } : null
}

/**
 * `/investments` on a phone: two actions instead of the desktop tables — «Создать выплату» and, as on the desktop,
 * either «Собрать из заявок» (the investment mode) or «Подать заявку на вложение» (without it; also when the mode's
 * config does not load) — each on its own full-screen address. Until the mode is known the second action is not
 * shown, so it does not change under the finger. A notification's link
 * `?tab=<returns|investments>&open=<id>` loads only that list and opens the record's card; a record that is not there
 * is reported and `open` is dropped. The card has no «Переотправить»: resending approvals stays on the desktop.
 * Other parameters (`schedule=`) are ignored.
 */
export function InvestmentsMobilePage() {
  useMobileHeader({ title: 'Инвестиции' })
  const { token } = theme.useToken()
  const navigate = useNavigate()
  const { loading: accessLoading, hasAccess } = useModuleAccess()
  const allowed = !accessLoading && hasAccess('investments')
  const fundingMode = useInvestmentFundingModeStatus(allowed)

  const [searchParams, setSearchParams] = useSearchParams()
  const hasOpen = searchParams.has('open')
  const openId = Number(searchParams.get('open'))
  // No tab: the desktop opens its first tab, «Заявки на вложение».
  const tab = searchParams.get('tab') ?? 'investments'
  const [linked, setLinked] = useState<LinkedRecord | null>(null)
  // A link with `open` shows the loading state from the first paint, not the actions for a moment.
  const [linkLoading, setLinkLoading] = useState(hasOpen)

  const dropOpenRef = useRef<() => void>(() => undefined)
  dropOpenRef.current = () =>
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        next.delete('open')
        return next
      },
      { replace: true },
    )

  useEffect(() => {
    if (!hasOpen) {
      setLinked(null)
      setLinkLoading(false)
      return
    }
    const valid = Number.isInteger(openId) && openId > 0
    const notFound = () => {
      message.warning(valid ? `Запись #${openId} не найдена или нет доступа` : 'Запись не найдена или нет доступа')
      dropOpenRef.current()
    }
    if (!valid || (tab !== 'returns' && tab !== 'investments')) {
      setLinkLoading(false)
      notFound()
      return
    }
    let cancelled = false
    setLinkLoading(true)
    findLinkedRecord(tab, openId)
      .catch(() => null)
      .then((found) => {
        if (cancelled) return
        setLinkLoading(false)
        if (found) setLinked(found)
        else notFound()
      })
    return () => {
      cancelled = true
    }
  }, [hasOpen, openId, tab])

  const closeLinked = () => {
    setLinked(null)
    dropOpenRef.current()
  }

  if (accessLoading || linkLoading) return <MobileStateWidget state="loading" rows={2} />

  if (!allowed) {
    return (
      <MobileStateWidget
        state="empty"
        title="Раздел недоступен"
        description="Модуль «Инвестиции» не включён для вашей роли."
      />
    )
  }

  return (
    <div style={{ display: 'grid', gap: 16 }}>
      <MobileActionsTheme>
        <div style={{ display: 'grid', gap: 12 }}>
          <Button type="primary" block size="large" icon={<PlusOutlined />} style={{ height: 48 }} onClick={() => navigate(INVEST_RETURN_NEW_PATH)}>
            Создать выплату
          </Button>
          {fundingMode.loading ? null : fundingMode.enabled ? (
            <Button block size="large" icon={<MergeCellsOutlined />} style={{ height: 48 }} onClick={() => navigate(INVESTMENT_COLLECT_PATH)}>
              Собрать из заявок
            </Button>
          ) : (
            <Button block size="large" icon={<FileAddOutlined />} style={{ height: 48 }} onClick={() => navigate(INVESTMENT_NEW_PATH)}>
              Подать заявку на вложение
            </Button>
          )}
        </div>
      </MobileActionsTheme>
      <Typography.Text style={{ color: token.colorTextSecondary }}>
        Списки вложений, расписание и выплаты — в версии для компьютера.
      </Typography.Text>

      <InvestmentRecordDetailModal
        open={Boolean(linked)}
        onCancel={closeLinked}
        kind={linked?.kind ?? null}
        record={linked?.record ?? null}
        variant="portal"
        descriptionsLayout="vertical"
        allowResend={false}
      />
    </div>
  )
}
