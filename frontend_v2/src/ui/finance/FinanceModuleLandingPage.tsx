import { Card, Col, Row, Typography } from 'antd'
import { useNavigate } from 'react-router-dom'
import type { ReactNode } from 'react'

export type FinanceModuleTile = {
  key: string
  title: string
  subtitle: string
  path: string
  icon: ReactNode
}

type FinanceModuleLandingPageProps = {
  title: string
  tiles: FinanceModuleTile[]
}

export function FinanceModuleLandingPage({ title, tiles }: FinanceModuleLandingPageProps) {
  const navigate = useNavigate()
  return (
    <Card>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        {title}
      </Typography.Title>
      <Row gutter={[16, 16]}>
        {tiles.map((tile) => (
          <Col key={tile.key} xs={24} sm={12} lg={8}>
            <Card
              hoverable
              size="small"
              onClick={() => navigate(tile.path)}
              styles={{ body: { padding: 16 } }}
            >
              <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
                <span style={{ fontSize: 22, lineHeight: 1, color: '#1677ff' }} aria-hidden>
                  {tile.icon}
                </span>
                <div>
                  <Typography.Text strong style={{ display: 'block', marginBottom: 4 }}>
                    {tile.title}
                  </Typography.Text>
                  <Typography.Text type="secondary" style={{ fontSize: 13 }}>
                    {tile.subtitle}
                  </Typography.Text>
                </div>
              </div>
            </Card>
          </Col>
        ))}
      </Row>
    </Card>
  )
}
