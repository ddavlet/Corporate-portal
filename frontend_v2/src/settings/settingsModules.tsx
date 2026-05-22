import { BarChartOutlined, BankOutlined, FileTextOutlined, SettingOutlined, ShopOutlined, TeamOutlined } from '@ant-design/icons'
import type { ReactNode } from 'react'

export type SettingsModuleItem = {
  key: string
  title: string
  description: string
  path: string
  icon: ReactNode
  group: string
}

export type SettingsGroup = {
  key: string
  label: string
  description: string
  icon: ReactNode
}

export const SETTINGS_GROUPS: SettingsGroup[] = [
  {
    key: 'company',
    label: 'Компания',
    description: 'Интеграции, пользователи и роли.',
    icon: <SettingOutlined />,
  },
  {
    key: 'requests',
    label: 'Заявки',
    description: 'Форма создания заявок и этапы согласования.',
    icon: <FileTextOutlined />,
  },
  {
    key: 'investments',
    label: 'Инвестиции',
    description: 'Форма создания, согласование выплат и заявок на вложение.',
    icon: <TeamOutlined />,
  },
  {
    key: 'reports',
    label: 'Отчёты',
    description: 'Источники данных и параметры PnL и Cashflow.',
    icon: <BarChartOutlined />,
  },
  {
    key: 'finance',
    label: 'Финансы',
    description: 'Кошельки, кассы, банковские счета и корпкарты.',
    icon: <BankOutlined />,
  },
]

/** Extend this list when adding module-specific settings pages. */
export const SETTINGS_MODULES: SettingsModuleItem[] = [
  {
    key: 'tenant-integrations',
    title: 'Настройки компании',
    description: 'URL, actions и секреты интеграций по модулям компании.',
    path: '/settings/tenant-integration-config',
    icon: <SettingOutlined />,
    group: 'company',
  },
  {
    key: 'users-roles',
    title: 'Пользователи и роли',
    description: 'Роли участников компании (только для администратора tenant).',
    path: '/settings/users-roles',
    icon: <TeamOutlined />,
    group: 'company',
  },
  {
    key: 'requests-form',
    title: 'Форма создания',
    description: 'Типы оплаты, заявители, поставщики, назначения платежа и категории.',
    path: '/settings/request-form-config',
    icon: <FileTextOutlined />,
    group: 'requests',
  },
  {
    key: 'requests-approvals',
    title: 'Этапы согласования',
    description: 'Очередность и пользователи, которые согласуют заявку.',
    path: '/settings/request-approval-config',
    icon: <FileTextOutlined />,
    group: 'requests',
  },
  {
    key: 'investments-form',
    title: 'Форма создания',
    description: 'Типы выплат и использование компаний при создании записей по инвестициям.',
    path: '/settings/investment-form-config',
    icon: <FileTextOutlined />,
    group: 'investments',
  },
  {
    key: 'investments-approvals',
    title: 'Этапы согласования выплат',
    description: 'Очередность и пользователи, которые подтверждают выплату по инвестициям.',
    path: '/settings/investment-approval-config',
    icon: <FileTextOutlined />,
    group: 'investments',
  },
  {
    key: 'investments-project-approvals',
    title: 'Согласование заявок на вложение',
    description: 'Этапы согласования заявок на вложение в проект, в том числе уведомления в Telegram.',
    path: '/settings/investment-project-approval-config',
    icon: <FileTextOutlined />,
    group: 'investments',
  },
  {
    key: 'pnl-report',
    title: 'Отчёт PnL',
    description: 'Источник данных, начальный остаток PnL и параметры backend-PnL.',
    path: '/settings/pnl-report-config',
    icon: <BarChartOutlined />,
    group: 'reports',
  },
  {
    key: 'cashflow-report',
    title: 'Отчёт Cashflow',
    description: 'Источник данных, начальный остаток Cashflow; фильтры совместно с PnL.',
    path: '/settings/cashflow-report-config',
    icon: <BarChartOutlined />,
    group: 'reports',
  },
  {
    key: 'cash-registers',
    title: 'Кошельки и счета',
    description: 'Касса — формат номера расхода для заявок; банк (выписка), корпкарта: счета, остаток на 1 янв, удаление без движений.',
    path: '/settings/cash-registers',
    icon: <ShopOutlined />,
    group: 'finance',
  },
]
