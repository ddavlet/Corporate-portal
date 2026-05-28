import { AppstoreOutlined, ArrowDownOutlined, ArrowUpOutlined } from '@ant-design/icons'
import { ChannelBalancesSummary } from './ChannelBalancesSummary'
import { FinanceModuleLandingPage, type FinanceModuleTile } from './finance/FinanceModuleLandingPage'

const TILES: FinanceModuleTile[] = [
  {
    key: 'all',
    title: 'Все операции',
    subtitle: 'Расходы и доходы в одном списке',
    path: '/cash/all',
    icon: <AppstoreOutlined />,
  },
  {
    key: 'expenses',
    title: 'Расходы',
    subtitle: 'Списания из касс',
    path: '/cash/expenses',
    icon: <ArrowUpOutlined />,
  },
  {
    key: 'revenues',
    title: 'Доходы',
    subtitle: 'Поступления в кассы',
    path: '/cash/revenues',
    icon: <ArrowDownOutlined />,
  },
]

export function CashPage() {
  return (
    <>
      <FinanceModuleLandingPage title="Касса" tiles={TILES} />
      <div style={{ marginTop: 16 }}>
        <ChannelBalancesSummary channel="cash" />
      </div>
    </>
  )
}
