import { type ReactNode, useEffect, useMemo, useState } from 'react'
import { Typography } from 'antd'
import { useNavigate } from 'react-router-dom'

import { DEFAULT_INVESTMENT_FORM_CONFIG, getInvestmentFormConfig } from '../../lib/api'
import {
  BankOutlined,
  CalendarOutlined,
  RiseOutlined,
  TeamOutlined,
} from '@ant-design/icons'

type Tile = {
  key: string
  title: string
  subtitle: string
  path: string
  icon: ReactNode
  iconClass?: string
}

const TILES: Tile[] = [
  {
    key: 'companies',
    title: 'Компании',
    subtitle: 'Список инвестиционных компаний',
    path: '/tg/investments/companies',
    icon: <TeamOutlined />,
  },
  {
    key: 'projects',
    title: 'Вложения',
    subtitle: 'Инвестиции в проекты',
    path: '/tg/investments/projects',
    icon: <BankOutlined />,
    iconClass: 'tg-section-tile-icon--expense',
  },
  {
    key: 'schedule',
    title: 'Расписание',
    subtitle: 'График выплат',
    path: '/tg/investments/schedule',
    icon: <CalendarOutlined />,
  },
  {
    key: 'returns',
    title: 'Выплаты',
    subtitle: 'Фактические выплаты инвесторам',
    path: '/tg/investments/returns',
    icon: <RiseOutlined />,
    iconClass: 'tg-section-tile-icon--revenue',
  },
]

export function TgInvestmentsPage() {
  const navigate = useNavigate()
  const [usesCompanies, setUsesCompanies] = useState(true)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const cfg = await getInvestmentFormConfig()
        if (!cancelled) setUsesCompanies(cfg.uses_companies)
      } catch {
        if (!cancelled) setUsesCompanies(DEFAULT_INVESTMENT_FORM_CONFIG.uses_companies)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const tiles = useMemo(() => TILES.filter((t) => t.key !== 'companies' || usesCompanies), [usesCompanies])

  return (
    <div className="tg-investments-page">
      <Typography.Title level={4} style={{ margin: '0 0 16px', fontWeight: 700 }}>
        Инвестиции
      </Typography.Title>
      <div className="tg-section-landing">
        {tiles.map((tile) => (
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
