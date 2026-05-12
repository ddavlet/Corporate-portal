import { Typography } from 'antd'
import { useNavigate } from 'react-router-dom'
import { AppstoreOutlined, ArrowDownOutlined, ArrowUpOutlined } from '@ant-design/icons'

type Tile = {
  key: string
  title: string
  subtitle: string
  path: string
  icon: React.ReactNode
  iconClass?: string
}

const TILES: Tile[] = [
  {
    key: 'all',
    title: 'Все операции',
    subtitle: 'Расходы и доходы в одном списке',
    path: '/tg/cash/all',
    icon: <AppstoreOutlined />,
  },
  {
    key: 'expenses',
    title: 'Расходы',
    subtitle: 'Списания из касс',
    path: '/tg/cash/expenses',
    icon: <ArrowUpOutlined />,
    iconClass: 'tg-section-tile-icon--expense',
  },
  {
    key: 'revenues',
    title: 'Доходы',
    subtitle: 'Поступления в кассы',
    path: '/tg/cash/revenues',
    icon: <ArrowDownOutlined />,
    iconClass: 'tg-section-tile-icon--revenue',
  },
]

export function TgCashPage() {
  const navigate = useNavigate()
  return (
    <div className="tg-cash-page">
      <Typography.Title level={4} style={{ margin: '0 0 16px', fontWeight: 700 }}>
        Касса
      </Typography.Title>
      <div className="tg-section-landing">
        {TILES.map((tile) => (
          <button
            key={tile.key}
            type="button"
            className="tg-section-tile"
            onClick={() => navigate(tile.path)}
          >
            <span className={`tg-section-tile-icon ${tile.iconClass || ''}`.trim()} aria-hidden>
              {tile.icon}
            </span>
            <span className="tg-section-tile-text">
              <span className="tg-section-tile-title">{tile.title}</span>
              <span className="tg-section-tile-subtitle">{tile.subtitle}</span>
            </span>
          </button>
        ))}
      </div>
    </div>
  )
}
