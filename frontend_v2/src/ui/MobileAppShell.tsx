import { useCallback, useEffect, useMemo, useState, useSyncExternalStore, type ReactNode } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import type { MenuProps } from 'antd'
import { Badge, Button, ConfigProvider, Divider, Drawer, Menu, Space, Typography, theme } from 'antd'
import { ArrowLeftOutlined, LockOutlined, LogoutOutlined, MenuOutlined } from '@ant-design/icons'
import { useAuth } from './auth'
import { useModuleAccess } from './moduleAccess'
import { useCompany } from './company'
import { useActionItems } from '../lib/useActionItems'
import { ChangePasswordModal } from './user/ChangePasswordModal'
import { CompanySwitcherWidget } from './CompanySwitcherWidget'
import { NotificationsBellWidget } from './NotificationsBellWidget'
import { InstallAppPromptWidget } from './InstallAppPromptWidget'
import { MOBILE_ANTD_THEME } from './mobileTheme'
import { buildMobileMenu, findMobileMenuItem, type MobileMenuItem } from './mobileMenu'
import {
  MobileShellContext,
  createMobileHeaderStore,
  type MobileHeaderStore,
  type MobileShellContextValue,
  type UserIdStatus,
} from './mobileShell'

export const MOBILE_DRAWER_WIDTH = 312

type Props = {
  /** Company name (tenant name, or the switcher's company on the shared host). */
  appTitle: string
  userId: number | null
  userIdStatus: UserIdStatus
}

/**
 * Phone layout of the portal (below 768 px, and the installed app): a 56 px header with «Меню» or «Назад», the page
 * title, the company switcher and the bell; a left drawer with the sections; antd tokens for touch.
 */
export function MobileAppShell({ appTitle, userId, userIdStatus }: Props) {
  const { enabled: companySwitcher } = useCompany()
  const [menuOpen, setMenuOpen] = useState(false)
  const [passwordOpen, setPasswordOpen] = useState(false)
  const [switcherOpen, setSwitcherOpen] = useState(false)
  const [headerStore] = useState(createMobileHeaderStore)
  const location = useLocation()

  // A section picked in the drawer (or any navigation) closes it.
  useEffect(() => {
    setMenuOpen(false)
  }, [location.pathname])

  const openCompanySwitcher = useCallback(() => {
    if (companySwitcher) setSwitcherOpen(true)
  }, [companySwitcher])

  const shellValue = useMemo<MobileShellContextValue>(
    () => ({ userId, userIdStatus, openCompanySwitcher, headerStore }),
    [userId, userIdStatus, openCompanySwitcher, headerStore],
  )

  return (
    <ConfigProvider theme={MOBILE_ANTD_THEME}>
      <MobileShellContext.Provider value={shellValue}>
        <MobileShellFrame>
          <MobileHeaderBar
            store={headerStore}
            appTitle={appTitle}
            menuOpen={menuOpen}
            onOpenMenu={() => setMenuOpen(true)}
            switcherOpen={switcherOpen}
            onSwitcherOpenChange={setSwitcherOpen}
          />
          <main className="m-content">
            {/* «Установить приложение»: only on a phone browser that can install; hidden for good once closed. */}
            <InstallAppPromptWidget />
            <Outlet />
          </main>
          <MobileNavDrawer
            open={menuOpen}
            onClose={() => setMenuOpen(false)}
            appTitle={appTitle}
            onChangePassword={() => {
              setMenuOpen(false)
              setPasswordOpen(true)
            }}
          />
          <ChangePasswordModal open={passwordOpen} onClose={() => setPasswordOpen(false)} />
        </MobileShellFrame>
      </MobileShellContext.Provider>
    </ConfigProvider>
  )
}

function MobileShellFrame({ children }: { children: ReactNode }) {
  const { token } = theme.useToken()
  return (
    <div className="m-root m-shell" data-testid="mobile-shell" style={{ background: token.colorBgLayout }}>
      {children}
    </div>
  )
}

type HeaderBarProps = {
  store: MobileHeaderStore
  appTitle: string
  menuOpen: boolean
  onOpenMenu: () => void
  switcherOpen: boolean
  onSwitcherOpenChange: (open: boolean) => void
}

function hasPortalPageBefore(): boolean {
  if (typeof window === 'undefined') return false
  const state: unknown = window.history.state
  const idx = state && typeof state === 'object' ? (state as { idx?: unknown }).idx : undefined
  return typeof idx === 'number' && idx > 0
}

function MobileHeaderBar({ store, appTitle, menuOpen, onOpenMenu, switcherOpen, onSwitcherOpenChange }: HeaderBarProps) {
  const { token } = theme.useToken()
  const navigate = useNavigate()
  const location = useLocation()
  const { count } = useActionItems()
  const { enabled: companySwitcher } = useCompany()
  const config = useSyncExternalStore(store.subscribe, store.get, store.get)

  const title = config?.title ?? findMobileMenuItem(location.pathname)?.name ?? appTitle
  const back = config?.back

  const goBack = () => {
    if (!back) return
    // An earlier page of the portal is in this tab's history: go back to it (the feed restores its state). The
    // router numbers its entries in history.state.idx; idx 0 is the first page of the tab, even after a
    // <Navigate replace> (login, «/»), so going back from there would leave the portal.
    if (hasPortalPageBefore()) navigate(-1)
    else navigate(back, { replace: true })
  }

  return (
    <header
      className="m-header"
      style={{ background: token.colorBgContainer, borderBottom: `1px solid ${token.colorBorderSecondary}` }}
    >
      {back ? (
        <Button type="text" className="m-header__button" icon={<ArrowLeftOutlined />} aria-label="Назад" onClick={goBack} />
      ) : (
        <Button
          type="text"
          className="m-header__button"
          icon={<MenuOutlined />}
          aria-label="Меню"
          aria-haspopup="dialog"
          aria-expanded={menuOpen}
          onClick={onOpenMenu}
        />
      )}
      <h1 className="m-header__title m-ellipsis" title={title}>
        {title}
      </h1>
      <div className="m-header__actions">
        {companySwitcher ? (
          <CompanySwitcherWidget variant="mobile" open={switcherOpen} onOpenChange={onSwitcherOpenChange} />
        ) : null}
        <NotificationsBellWidget size="touch" count={count} onClick={() => navigate('/notifications')} />
        {config?.action ?? null}
      </div>
    </header>
  )
}

type NavDrawerProps = {
  open: boolean
  onClose: () => void
  appTitle: string
  onChangePassword: () => void
}

function MobileNavDrawer({ open, onClose, appTitle, onChangePassword }: NavDrawerProps) {
  const { token } = theme.useToken()
  const navigate = useNavigate()
  const location = useLocation()
  const { logout, username } = useAuth()
  const { hasAccess } = useModuleAccess()
  const { count } = useActionItems()
  const menu = useMemo(() => buildMobileMenu(hasAccess), [hasAccess])

  const toMenuItem = (item: MobileMenuItem): NonNullable<MenuProps['items']>[number] => {
    const Icon = item.icon
    const badge = item.path === '/requests' && count > 0
    return {
      key: item.path,
      icon: <Icon aria-hidden />,
      label: badge ? (
        <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
          <span>{item.name}</span>
          <Badge count={count} overflowCount={99} size="small" data-testid="mobile-menu-requests-badge" />
        </span>
      ) : (
        item.name
      ),
    }
  }

  const items: MenuProps['items'] = [
    { type: 'group', key: 'main', label: 'Основное', children: menu.main.map(toMenuItem) },
    ...(menu.desktop.length > 0
      ? [{ type: 'group' as const, key: 'desktop', label: 'На компьютере', children: menu.desktop.map(toMenuItem) }]
      : []),
  ]

  const selected = findMobileMenuItem(location.pathname)?.path

  return (
    <Drawer
      open={open}
      onClose={onClose}
      placement="left"
      width={MOBILE_DRAWER_WIDTH}
      rootClassName="m-drawer"
      closable={{ 'aria-label': 'Закрыть меню' }}
      title={
        <div style={{ minWidth: 0 }}>
          <Typography.Text strong className="m-ellipsis" style={{ display: 'block' }} data-testid="mobile-menu-company">
            {appTitle}
          </Typography.Text>
          {username ? (
            <Typography.Text className="m-ellipsis" style={{ display: 'block', color: token.colorTextSecondary, fontWeight: 400 }}>
              {username}
            </Typography.Text>
          ) : null}
        </div>
      }
    >
      <nav aria-label="Разделы">
        <Menu
          mode="inline"
          items={items}
          selectedKeys={selected ? [selected] : []}
          style={{ borderInlineEnd: 0 }}
          onClick={({ key }) => {
            onClose()
            navigate(String(key))
          }}
        />
      </nav>
      <Divider style={{ margin: '8px 0' }} />
      <Space direction="vertical" size={4} style={{ width: '100%' }}>
        <Button type="text" block icon={<LockOutlined />} onClick={onChangePassword} style={{ justifyContent: 'flex-start' }}>
          Сменить пароль
        </Button>
        <Button
          type="text"
          block
          icon={<LogoutOutlined />}
          style={{ justifyContent: 'flex-start' }}
          onClick={() => {
            onClose()
            logout()
            navigate('/login', { replace: true })
          }}
        >
          Выйти
        </Button>
      </Space>
    </Drawer>
  )
}
