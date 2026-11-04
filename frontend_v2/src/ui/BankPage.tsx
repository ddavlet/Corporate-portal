import { AppstoreOutlined, ArrowDownOutlined, ArrowUpOutlined } from '@ant-design/icons'
import { Card, Space, Typography } from 'antd'
import { Link } from 'react-router-dom'
import { KapitalbankPendingAccountsWidget } from './KapitalbankPendingAccountsWidget'
import { BankAccountsList } from './bank/BankAccountsList'

export function BankPage() {
  return (
    <>
      <Card>
        <Typography.Title level={4} style={{ marginTop: 0 }}>
          Банк
        </Typography.Title>
        <BankAccountsList />
        <Space wrap size={[16, 8]} style={{ marginTop: 16 }}>
          <Typography.Text type="secondary">По всем счетам:</Typography.Text>
          <Link to="/bank/all">
            <AppstoreOutlined /> Все операции
          </Link>
          <Link to="/bank/expenses">
            <ArrowUpOutlined /> Расходы
          </Link>
          <Link to="/bank/revenues">
            <ArrowDownOutlined /> Доходы
          </Link>
        </Space>
      </Card>
      <KapitalbankPendingAccountsWidget style={{ marginTop: 16 }} />
    </>
  )
}
