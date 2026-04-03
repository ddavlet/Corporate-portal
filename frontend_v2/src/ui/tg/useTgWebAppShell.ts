import { useEffect } from 'react'

const CSS_VARS = [
  '--tg-bg',
  '--tg-secondary-bg',
  '--tg-text',
  '--tg-hint',
  '--tg-link',
  '--tg-button',
  '--tg-button-text',
  '--tg-row-bg',
] as const

function applyTelegramTheme() {
  const tw = typeof window !== 'undefined' ? window.Telegram?.WebApp : undefined
  if (!tw) return

  const root = document.documentElement
  const p = tw.themeParams

  const setVar = (name: string, value?: string) => {
    if (value) root.style.setProperty(name, value)
    else root.style.removeProperty(name)
  }

  if (p) {
    setVar('--tg-bg', p.bg_color)
    setVar('--tg-secondary-bg', p.secondary_bg_color)
    setVar('--tg-text', p.text_color)
    setVar('--tg-hint', p.hint_color)
    setVar('--tg-link', p.link_color)
    setVar('--tg-button', p.button_color)
    setVar('--tg-button-text', p.button_text_color)
    if (p.secondary_bg_color) {
      setVar('--tg-row-bg', p.secondary_bg_color)
    } else {
      setVar('--tg-row-bg', tw.colorScheme === 'dark' ? '#2c2c2e' : '#ffffff')
    }
  } else if (tw.colorScheme === 'dark') {
    setVar('--tg-row-bg', '#2c2c2e')
  }

  const isDark = tw.colorScheme === 'dark'
  root.classList.toggle('tg-twa-dark', isDark)
  root.style.colorScheme = isDark ? 'dark' : 'light'

  try {
    if (p?.bg_color) tw.setBackgroundColor?.(p.bg_color)
    if (p?.secondary_bg_color) tw.setHeaderColor?.(p.secondary_bg_color)
  } catch {
    /* ignore */
  }
}

/** CSS-переменные темы Telegram + класс тёмной темы + смена темы в клиенте. После применения CSS вызывается onThemeApplied (например обновление ConfigProvider Ant Design). */
export function useTgWebAppShell(onThemeApplied?: () => void) {
  useEffect(() => {
    const tw = typeof window !== 'undefined' ? window.Telegram?.WebApp : undefined

    const run = () => {
      applyTelegramTheme()
      onThemeApplied?.()
    }

    if (!tw) {
      run()
      return
    }

    run()
    tw.onEvent?.('themeChanged', run)

    return () => {
      tw.offEvent?.('themeChanged', run)
      const root = document.documentElement
      root.classList.remove('tg-twa-dark')
      root.style.removeProperty('color-scheme')
      CSS_VARS.forEach((k) => root.style.removeProperty(k))
    }
  }, [onThemeApplied])
}
