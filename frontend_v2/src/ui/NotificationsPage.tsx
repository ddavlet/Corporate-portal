import { useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { Alert, Button, Card, Empty, List, Skeleton, Space, Tag, Typography, theme } from 'antd'
import type { GlobalToken } from 'antd'
import { RightOutlined } from '@ant-design/icons'
import { actionItemTag, type ActionItem, type ActionItemKind } from '../lib/actionItemsApi'
import { formatRequestDate } from '../lib/requestUtils'
import { useActionItems } from '../lib/useActionItems'
import { useCompany } from './company'
import { usePortalMobileMode } from '../lib/useIsPhone'

const KIND_LABELS: Record<ActionItemKind, string> = {
  request: 'Заявка',
  invest_return: 'Выплата инвестиции',
  project_investment: 'Вложение в проект',
}

/**
 * Tag colours from the antd palette, text dark enough for 4.5:1 on the light background at 12 px
 * (antd's own gold and green tags are lighter). Gold needs shade 9: gold-8 on gold-1 is about 4.3:1.
 */
function kindTagStyle(kind: ActionItemKind, token: GlobalToken) {
  if (kind === 'invest_return') return { color: token.gold9, background: token.gold1, borderColor: token.gold3 }
  if (kind === 'project_investment') return { color: token.green8, background: token.green1, borderColor: token.green3 }
  return { color: token.blue7, background: token.blue1, borderColor: token.blue3 }
}

/**
 * Supporting text. Typography's type="secondary" uses colorTextDescription (45 % black, about 3.4:1 on white);
 * colorTextSecondary (65 % black, about 6:1) keeps the hierarchy and passes 4.5:1.
 */
function MutedText({ children }: { children: ReactNode }) {
  const { token } = theme.useToken()
  return <Typography.Text style={{ color: token.colorTextSecondary }}>{children}</Typography.Text>
}

const STEP_TYPE_LABELS: Record<string, string> = {
  serial: 'согласование',
  payment: 'оплата',
  confirmation: 'подтверждение',
}

const amountFormatter = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 })

function formatAmount(item: ActionItem): string {
  const value = Number(item.amount)
  const text = Number.isFinite(value) ? amountFormatter.format(value) : String(item.amount || '—')
  return item.currency ? `${text} ${item.currency}` : text
}

function stepText(item: ActionItem): string {
  const label = STEP_TYPE_LABELS[item.step_type]
  return label ? `Шаг ${item.step}: ${label}` : `Шаг ${item.step}`
}

function ActionItemRow({ item }: { item: ActionItem }) {
  const { token } = theme.useToken()
  const isInvestment = item.kind !== 'request'
  return (
    <List.Item style={{ padding: 0 }}>
      <Link
        to={item.link}
        data-action-item={actionItemTag(item)}
        style={{ display: 'flex', alignItems: 'center', gap: 12, width: '100%', padding: '12px 0', color: 'inherit' }}
      >
        <Space direction="vertical" size={4} style={{ flex: 1, minWidth: 0 }}>
          <Space size={8} wrap>
            <Tag style={{ marginInlineEnd: 0, ...kindTagStyle(item.kind, token) }}>
              {KIND_LABELS[item.kind] ?? item.kind}
            </Tag>
            {item.tenant ? (
              <Tag style={{ marginInlineEnd: 0, whiteSpace: 'normal', overflowWrap: 'anywhere' }}>
                {item.tenant.name || item.tenant.subdomain}
              </Tag>
            ) : null}
            {item.type_label ? <MutedText>{item.type_label}</MutedText> : null}
          </Space>
          <Typography.Text strong style={{ overflowWrap: 'anywhere' }}>
            {item.title}
          </Typography.Text>
          <Space size={[16, 4]} wrap>
            <Typography.Text>{formatAmount(item)}</Typography.Text>
            <MutedText>{stepText(item)}</MutedText>
            <MutedText>{`Создана ${formatRequestDate(item.created_at)}`}</MutedText>
          </Space>
          {isInvestment ? (
            <MutedText>Решение принимается в Telegram</MutedText>
          ) : null}
        </Space>
        <RightOutlined aria-hidden style={{ flexShrink: 0 }} />
      </Link>
    </List.Item>
  )
}

export function NotificationsPage() {
  const { items, count, loading, error, refresh } = useActionItems()
  const { enabled: allCompanies } = useCompany()
  const isMobile = usePortalMobileMode()
  const [retrying, setRetrying] = useState(false)

  const retry = async () => {
    setRetrying(true)
    try {
      await refresh()
    } finally {
      setRetrying(false)
    }
  }

  return (
    <Card variant={isMobile ? 'borderless' : undefined} styles={isMobile ? { body: { padding: 16 } } : undefined}>
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        <div>
          {/* Phone: the header already says «Уведомления». */}
          {isMobile ? null : (
            <Typography.Title level={4} style={{ margin: 0 }}>
              Уведомления
            </Typography.Title>
          )}
          <MutedText>
            {count > 0
              ? `Требуется ваше действие: ${count}`
              : allCompanies
                ? 'Заявки и инвестиции во всех ваших компаниях, где сейчас ваш шаг согласования'
                : 'Заявки и инвестиции, где сейчас ваш шаг согласования'}
          </MutedText>
        </div>

        {/* Phone: the place of the future «Включить уведомления» button (Web Push). */}
        {isMobile ? <div data-testid="push-subscribe-slot" /> : null}

        {error ? (
          <Alert
            type="error"
            showIcon
            message="Не удалось загрузить уведомления"
            action={
              <Button size="small" onClick={() => void retry()} loading={retrying}>
                Повторить
              </Button>
            }
          />
        ) : null}

        {loading ? (
          <Skeleton active paragraph={{ rows: 3 }} />
        ) : !error && items.length === 0 ? (
          <Empty description="Сейчас ничего не ждёт вашего действия" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        ) : items.length > 0 ? (
          <List
            dataSource={items}
            rowKey={(item) => actionItemTag(item)}
            renderItem={(item) => <ActionItemRow item={item} />}
          />
        ) : null}
      </Space>
    </Card>
  )
}
