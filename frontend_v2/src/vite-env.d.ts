/// <reference types="vite/client" />

interface TelegramWebAppUser {
  id: number
  first_name?: string
  last_name?: string
  username?: string
  language_code?: string
}

interface TelegramThemeParams {
  bg_color?: string
  text_color?: string
  hint_color?: string
  link_color?: string
  button_color?: string
  button_text_color?: string
  secondary_bg_color?: string
}

interface TelegramWebAppInitDataUnsafe {
  start_param?: string
  user?: TelegramWebAppUser
  [key: string]: unknown
}

interface TelegramMainButton {
  setText: (text: string) => void
  show: () => void
  hide: () => void
  enable: () => void
  disable: () => void
  showProgress: () => void
  hideProgress: () => void
  onClick: (callback: () => void) => void
  offClick: (callback: () => void) => void
}

type TelegramHapticImpact = 'light' | 'medium' | 'heavy' | 'rigid' | 'soft'
type TelegramHapticNotification = 'error' | 'success' | 'warning'

interface TelegramHapticFeedback {
  impactOccurred: (style: TelegramHapticImpact) => void
  notificationOccurred: (type: TelegramHapticNotification) => void
  selectionChanged: () => void
}

interface TelegramWebApp {
  initData: string
  initDataUnsafe: TelegramWebAppInitDataUnsafe
  ready: () => void
  expand?: () => void
  close?: () => void
  themeParams?: TelegramThemeParams
  colorScheme?: 'light' | 'dark'
  setHeaderColor?: (color: string) => void
  setBackgroundColor?: (color: string) => void
  onEvent?: (eventType: string, callback: () => void) => void
  offEvent?: (eventType: string, callback: () => void) => void
  MainButton?: TelegramMainButton
  HapticFeedback?: TelegramHapticFeedback
}

interface Window {
  Telegram?: {
    WebApp: TelegramWebApp
  }
}
