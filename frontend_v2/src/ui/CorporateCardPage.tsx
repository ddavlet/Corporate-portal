import { AppstoreOutlined, ArrowDownOutlined, ArrowUpOutlined } from '@ant-design/icons'
import { ChannelBalancesSummary } from './ChannelBalancesSummary'
import { FinanceModuleLandingPage, type FinanceModuleTile } from './finance/FinanceModuleLandingPage'

const TILES: FinanceModuleTile[] = [
  {
    key: 'all',
    title: 'Все операции',
    subtitle: 'Расходы и доходы в одном списке',
    path: '/corporate-card/all',
    icon: <AppstoreOutlined />,
  },
  {
    key: 'expenses',
    title: 'Расходы',
    subtitle: 'Списания по корпоративной карте',
    path: '/corporate-card/expenses',
    icon: <ArrowUpOutlined />,
  },
  {
    key: 'revenues',
    title: 'Доходы',
    subtitle: 'Пополнения корпоративной карты',
    path: '/corporate-card/revenues',
    icon: <ArrowDownOutlined />,
  },
]

export function CorporateCardPage() {
  return (
    <>
      <FinanceModuleLandingPage title="Корпоративная карта" tiles={TILES} />
      <div style={{ marginTop: 16 }}>
        <ChannelBalancesSummary channel="corporate_card" />
      </div>
    </>
  )
}
