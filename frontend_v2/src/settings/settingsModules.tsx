import { BarChartOutlined, FileTextOutlined, SettingOutlined, ShopOutlined, TeamOutlined } from '@ant-design/icons'
import type { ReactNode } from 'react'

export type SettingsModuleItem = {
  key: string
  title: string
  description: string
  path: string
  icon: ReactNode
}

/** Extend this list when adding module-specific settings pages. */
export const SETTINGS_MODULES: SettingsModuleItem[] = [
  {
    key: 'requests-form',
    title: 'Заявки — форма создания',
    description: 'Типы оплаты, заявители, поставщики, назначения платежа и категории.',
    path: '/settings/request-form-config',
    icon: <FileTextOutlined />,
  },
  {
    key: 'requests-approvals',
    title: 'Заявки — этапы согласования',
    description: 'Очередность и пользователи, которые согласуют заявку.',
    path: '/settings/request-approval-config',
    icon: <FileTextOutlined />,
  },
  {
    key: 'tenant-integrations',
    title: 'Интеграции tenant',
    description: 'URL, actions и секреты интеграций по модулям компании.',
    path: '/settings/tenant-integration-config',
    icon: <SettingOutlined />,
  },
  {
    key: 'pnl-report',
    title: 'Отчёт PnL',
    description: 'Источник данных, начальный остаток PnL и параметры backend-PnL.',
    path: '/settings/pnl-report-config',
    icon: <BarChartOutlined />,
  },
  {
    key: 'cashflow-report',
    title: 'Отчёт Cashflow',
    description: 'Источник данных, начальный остаток Cashflow; фильтры совместно с PnL.',
    path: '/settings/cashflow-report-config',
    icon: <BarChartOutlined />,
  },
  {
    key: 'users-roles',
    title: 'Настройки пользователей',
    description: 'Роли участников компании (только для администратора tenant).',
    path: '/settings/users-roles',
    icon: <TeamOutlined />,
  },
  {
    key: 'investments-form',
    title: 'Инвестиции — форма создания',
    description: 'Типы выплат и использование компаний при создании записей по инвестициям.',
    path: '/settings/investment-form-config',
    icon: <FileTextOutlined />,
  },
  {
    key: 'investments-approvals',
    title: 'Инвестиции — этапы согласования',
    description: 'Очередность и пользователи, которые подтверждают выплату по инвестициям.',
    path: '/settings/investment-approval-config',
    icon: <FileTextOutlined />,
  },
  {
    key: 'investments-project-approvals',
    title: 'Инвестиции — заявки на вложение',
    description: 'Этапы согласования заявок на вложение в проект, в том числе уведомления в Telegram.',
    path: '/settings/investment-project-approval-config',
    icon: <FileTextOutlined />,
  },
  {
    key: 'cash-registers',
    title: 'Кошельки',
    description:
      'Касса — формат номера расхода для заявок; банк (выписка), корпкарта: счета, остаток на 1 янв, удаление без движений.',
    path: '/settings/cash-registers',
    icon: <ShopOutlined />,
  },
]
