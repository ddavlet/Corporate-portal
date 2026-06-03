import { Typography } from 'antd'
import { useNavigate } from 'react-router-dom'
import {
  BankOutlined,
  CheckSquareOutlined,
  DollarOutlined,
  FileTextOutlined,
  RiseOutlined,
} from '@ant-design/icons'
import { useModuleAccess } from '../moduleAccess'
import { tgHaptic } from './tgHaptic'

type Tile = {
  key: string
  title: string
  subtitle: string
  path: string
  moduleKey: string
  icon: React.ReactNode
  iconClass?: string
}

const TILES: Tile[] = [
  {
    key: 'requests',
    title: 'Заявки',
    subtitle: 'Заявки на оплату',
    path: '/tg/requests',
    moduleKey: 'requests',
    icon: <FileTextOutlined />,
  },
  {
    key: 'cash',
    title: 'Касса',
    subtitle: 'Расходы и доходы по кассам',
    path: '/tg/cash',
    moduleKey: 'cash',
    icon: <DollarOutlined />,
    iconClass: 'tg-section-tile-icon--expense',
  },
  {
    key: 'bank',
    title: 'Банк',
    subtitle: 'Движения по банковским счетам',
    path: '/tg/bank',
    moduleKey: 'bank',
    icon: <BankOutlined />,
  },
  {
    key: 'investments',
    title: 'Инвестиции',
    subtitle: 'Компании, вложения, выплаты',
    path: '/tg/investments',
    moduleKey: 'investments',
    icon: <RiseOutlined />,
    iconClass: 'tg-section-tile-icon--revenue',
  },
  {
    key: 'tasks',
    title: 'Задачи',
    subtitle: 'Доска задач команды',
    path: '/tg/tasks',
    moduleKey: 'tasks',
    icon: <CheckSquareOutlined />,
  },
]

export function TgHomePage() {
  const navigate = useNavigate()
  const { hasAccess } = useModuleAccess()
  const visible = TILES.filter((tile) => hasAccess(tile.moduleKey))

  return (
    <div className="tg-home-page">
      <Typography.Title level={4} style={{ margin: '0 0 16px', fontWeight: 700 }}>
        Главная
      </Typography.Title>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 16 }}>
        Выберите раздел.
      </Typography.Paragraph>
      <div className="tg-section-landing">
        {visible.map((tile) => (
          <button
            key={tile.key}
            type="button"
            className="tg-section-tile"
            onClick={() => { tgHaptic.tap(); navigate(tile.path) }}
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
        {visible.length === 0 ? (
          <Typography.Paragraph type="secondary" style={{ textAlign: 'center', padding: '16px 8px' }}>
            Нет доступных модулей.
          </Typography.Paragraph>
        ) : null}
      </div>
    </div>
  )
}
