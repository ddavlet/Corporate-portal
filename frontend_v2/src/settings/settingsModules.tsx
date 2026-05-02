import { FileTextOutlined, SettingOutlined, ShopOutlined } from '@ant-design/icons'
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
    key: 'investments-approvals',
    title: 'Инвестиции — этапы согласования',
    description: 'Очередность и пользователи, которые подтверждают выплату по инвестициям.',
    path: '/settings/investment-approval-config',
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
