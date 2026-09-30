import { SettingOutlined } from '@ant-design/icons'
import { Button, Card, Tag, Typography } from 'antd'
import { Link } from 'react-router-dom'
import type { ReportCard } from './reportCards'
import './ReportCardWidget.css'

type Props = {
  card: ReportCard
  /** The card's page with the view the user left it in. */
  href: string
  /** Opens the rules of the card's report; null for users who may not change them. */
  onOpenRules: (() => void) | null
}

/** A report on «Отчёты»: nothing is loaded until the card is opened. */
export function ReportCardWidget({ card, href, onOpenRules }: Props) {
  return (
    <Card
      hoverable
      style={{ height: '100%' }}
      title={
        // The link covers the whole card (ReportCardWidget.css): every click on the card is a plain link click.
        <Link className="report-card-link" to={href}>
          {card.title}
        </Link>
      }
      extra={
        onOpenRules ? (
          <Button
            className="report-card-rules"
            type="text"
            icon={<SettingOutlined />}
            aria-label={`Правила отчёта «${card.title}»`}
            onClick={() => onOpenRules()}
          />
        ) : null
      }
    >
      <Tag>{card.templateLabel}</Tag>
      <Typography.Paragraph type="secondary" style={{ margin: '8px 0 0' }}>
        {card.description}
      </Typography.Paragraph>
    </Card>
  )
}
