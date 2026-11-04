import { useCallback, useEffect, useState } from 'react'
import { Button, message } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'

import type { InvestmentApprovalItem } from '../../lib/api'

const RESEND_MAX = 3

type Props = {
  item: InvestmentApprovalItem
  resend: (approvalId: number) => Promise<void>
  onResent: () => void
}

/** Переотправка Telegram-карточки согласования — как у заявок на расходы. */
export function InvestmentApprovalResendButton({ item, resend, onResent }: Props) {
  const [loading, setLoading] = useState(false)
  const [secondsLeft, setSecondsLeft] = useState(0)

  const computeSecondsLeft = useCallback(() => {
    if (!item.resend_available_at) return 0
    const diff = Math.ceil((new Date(item.resend_available_at).getTime() - Date.now()) / 1000)
    return Math.max(0, diff)
  }, [item.resend_available_at])

  useEffect(() => {
    const secs = computeSecondsLeft()
    setSecondsLeft(secs)
    if (secs <= 0) return
    const timer = setInterval(() => {
      const remaining = computeSecondsLeft()
      setSecondsLeft(remaining)
      if (remaining <= 0) clearInterval(timer)
    }, 1000)
    return () => clearInterval(timer)
  }, [computeSecondsLeft])

  if (!item.can_resend) return null

  const inCooldown = secondsLeft > 0
  const left = RESEND_MAX - (item.resend_count ?? 0)

  const handleResend = async () => {
    setLoading(true)
    try {
      await resend(item.id)
      message.success('Сообщение переотправлено')
      onResent()
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Не удалось переотправить'
      if (msg.includes('429') || msg.toLowerCase().includes('подождите')) {
        message.warning(msg)
      } else {
        message.error(msg)
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <Button
      size="small"
      icon={<ReloadOutlined />}
      loading={loading}
      disabled={inCooldown}
      title={
        inCooldown
          ? `Переотправка доступна через ${secondsLeft}с`
          : `Переотправить карточку (осталось ${left} из ${RESEND_MAX})`
      }
      onClick={() => void handleResend()}
    >
      {inCooldown ? `Подождите ${secondsLeft}с` : `Переотправить (${left} из ${RESEND_MAX})`}
    </Button>
  )
}
