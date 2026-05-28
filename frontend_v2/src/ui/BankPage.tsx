import { AppstoreOutlined, ArrowDownOutlined, ArrowUpOutlined } from '@ant-design/icons'
import { ChannelBalancesSummary } from './ChannelBalancesSummary'
import { FinanceModuleLandingPage, type FinanceModuleTile } from './finance/FinanceModuleLandingPage'

const TILES: FinanceModuleTile[] = [
  {
    key: 'all',
    title: 'Все операции',
    subtitle: 'Расходы и доходы в одном списке',
    path: '/bank/all',
    icon: <AppstoreOutlined />,
  },
  {
    key: 'expenses',
    title: 'Расходы',
    subtitle: 'Списания по счетам',
    path: '/bank/expenses',
    icon: <ArrowUpOutlined />,
  },
  {
    key: 'revenues',
    title: 'Доходы',
    subtitle: 'Поступления на счета',
    path: '/bank/revenues',
    icon: <ArrowDownOutlined />,
  },
]

export function BankPage() {
  return (
    <>
      <FinanceModuleLandingPage title="Банк" tiles={TILES} />
      <div style={{ marginTop: 16 }}>
        <ChannelBalancesSummary channel="bank" />
      </div>
    </>
  )
}
