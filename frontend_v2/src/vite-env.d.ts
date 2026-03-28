/// <reference types="vite/client" />

interface TelegramWebAppUser {
  id: number
  first_name?: string
  last_name?: string
  username?: string
  language_code?: string
}

interface TelegramWebApp {
  initData: string
  initDataUnsafe: Record<string, unknown>
  ready: () => void
  expand?: () => void
}

interface Window {
  Telegram?: {
    WebApp: TelegramWebApp
  }
}
