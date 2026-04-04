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
    key: 'cash-registers',
    title: 'Кассы',
    description: 'Справочник касс и остаток на начало года по кошельку.',
    path: '/settings/cash-registers',
    icon: <ShopOutlined />,
  },
]
