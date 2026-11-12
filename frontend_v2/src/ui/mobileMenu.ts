import type { ComponentType } from 'react'
import {
  BankOutlined,
  BarChartOutlined,
  BellOutlined,
  CheckSquareOutlined,
  ContactsOutlined,
  CreditCardOutlined,
  DollarOutlined,
  FileTextOutlined,
  FundOutlined,
  RiseOutlined,
  SolutionOutlined,
  TeamOutlined,
} from '@ant-design/icons'

export type MobileMenuItem = {
  path: string
  name: string
  icon: ComponentType<{ 'aria-hidden'?: boolean }>
  /** Module that must be enabled for the user (useModuleAccess); none: always shown. */
  moduleKey?: string
}

export type MobileMenu = {
  /** Sections of the phone app: only «Заявки» and «Инвестиции». */
  main: MobileMenuItem[]
}

const MAIN_ITEMS: MobileMenuItem[] = [
  { path: '/requests', name: 'Заявки', icon: FileTextOutlined, moduleKey: 'requests' },
  { path: '/investments', name: 'Инвестиции', icon: RiseOutlined, moduleKey: 'investments' },
]

/**
 * Sections that are not in the phone menu but still get a header title when opened by a link: «Уведомления» (the
 * bell opens it) and the desktop-only sections, which show the «Раздел доступен на компьютере» placeholder.
 */
const OTHER_SECTIONS: MobileMenuItem[] = [
  { path: '/notifications', name: 'Уведомления', icon: BellOutlined },
  { path: '/tasks', name: 'Задачи', icon: CheckSquareOutlined, moduleKey: 'tasks' },
  { path: '/cash', name: 'Касса', icon: DollarOutlined, moduleKey: 'cash' },
  { path: '/bank', name: 'Банк', icon: BankOutlined, moduleKey: 'bank' },
  { path: '/corporate-card', name: 'Корп. карта', icon: CreditCardOutlined, moduleKey: 'corporate_card' },
  { path: '/payroll', name: 'Начисления ЗП', icon: TeamOutlined, moduleKey: 'payroll' },
  { path: '/reports', name: 'Отчёты', icon: BarChartOutlined, moduleKey: 'reports' },
  { path: '/clients-debt', name: 'Долги клиентов', icon: ContactsOutlined, moduleKey: 'clients_debt' },
  { path: '/budgets', name: 'Бюджеты', icon: FundOutlined, moduleKey: 'budgets' },
  { path: '/contracts', name: 'Договоры', icon: SolutionOutlined, moduleKey: 'contracts' },
]

/**
 * Menu of the phone layout. There is no «Панель», «Настройки» or «Админка» on a phone, whatever the user's rights:
 * the function does not even take them.
 */
export function buildMobileMenu(hasAccess: (moduleKey: string) => boolean): MobileMenu {
  const allowed = (item: MobileMenuItem) => !item.moduleKey || hasAccess(item.moduleKey)
  return { main: MAIN_ITEMS.filter(allowed) }
}

/** The menu item a path belongs to (`/requests/12` → «Заявки»). */
export function findMobileMenuItem(pathname: string): MobileMenuItem | null {
  return (
    [...MAIN_ITEMS, ...OTHER_SECTIONS].find((item) => pathname === item.path || pathname.startsWith(`${item.path}/`)) ??
    null
  )
}

/** Sections outside the phone menu (or under a menu item but with a name of their own) that open the placeholder. */
const OFF_MENU_SECTIONS: { path: string; name: string }[] = [
  { path: '/requests/audit', name: 'Аудит месяцев' },
  { path: '/requests/auto-config', name: 'Автозаявки' },
  { path: '/settings', name: 'Настройки' },
  { path: '/admin', name: 'Админка' },
]

const matchesSection = (pathname: string, path: string) => pathname === path || pathname.startsWith(`${path}/`)

/** Header title of a section on the phone: its own name, else the menu item it belongs to (`/cash/all` → «Касса»). */
export function findMobileSectionTitle(pathname: string): string | null {
  return OFF_MENU_SECTIONS.find((section) => matchesSection(pathname, section.path))?.name ?? findMobileMenuItem(pathname)?.name ?? null
}
