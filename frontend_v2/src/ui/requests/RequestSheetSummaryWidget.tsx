import { Typography, theme } from 'antd'

export type RequestSheetSummary = {
  id: number
  title: string
  amount: string
  vendor?: string | null
}

/** Summary of the request at the top of a short confirmation sheet (payment, rejection): number, title, vendor, amount. */
export function RequestSheetSummaryWidget({ summary, testId }: { summary: RequestSheetSummary; testId?: string }) {
  const { token } = theme.useToken()
  return (
    <dl
      data-testid={testId}
      style={{
        margin: 0,
        padding: 12,
        display: 'grid',
        gap: 8,
        borderRadius: token.borderRadiusLG,
        background: token.colorFillQuaternary,
      }}
    >
      <SummaryRow label="Заявка" value={`#${summary.id} · ${summary.title || 'Без названия'}`} />
      {summary.vendor ? <SummaryRow label="Получатель" value={summary.vendor} /> : null}
      <SummaryRow label="Сумма" value={summary.amount} strong />
    </dl>
  )
}

function SummaryRow({ label, value, strong = false }: { label: string; value: string; strong?: boolean }) {
  const { token } = theme.useToken()
  return (
    <div style={{ display: 'grid', gap: 2, minWidth: 0 }}>
      <dt style={{ fontSize: 13, color: token.colorTextSecondary }}>{label}</dt>
      <dd style={{ margin: 0, overflowWrap: 'anywhere' }}>
        <Typography.Text strong={strong}>{value}</Typography.Text>
      </dd>
    </div>
  )
}
