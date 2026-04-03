import { theme, type ThemeConfig } from 'antd'

/** Сборка темы Ant Design из Telegram.WebApp (themeParams + colorScheme). Без Telegram — светлые значения по умолчанию. */
export function getTgAntdTheme(): ThemeConfig {
  const tw = typeof window !== 'undefined' ? window.Telegram?.WebApp : undefined
  const p = tw?.themeParams
  const isDark = tw?.colorScheme === 'dark'

  const algorithm = isDark ? theme.darkAlgorithm : theme.defaultAlgorithm

  const colorBgLayout = p?.bg_color ?? (isDark ? '#1c1c1e' : '#f5f5f5')
  const colorBgContainer = p?.secondary_bg_color ?? (isDark ? '#2c2c2e' : '#ffffff')
  const colorText = p?.text_color ?? (isDark ? 'rgba(255, 255, 255, 0.88)' : 'rgba(0, 0, 0, 0.88)')
  const colorTextSecondary =
    p?.hint_color ?? (isDark ? 'rgba(255, 255, 255, 0.45)' : 'rgba(0, 0, 0, 0.45)')
  const colorPrimary = p?.button_color ?? '#1677ff'
  const colorLink = p?.link_color ?? colorPrimary
  const colorBorder = isDark ? 'rgba(255, 255, 255, 0.12)' : 'rgba(0, 0, 0, 0.15)'

  return {
    algorithm,
    token: {
      borderRadius: 12,
      borderRadiusLG: 14,
      controlHeight: 44,
      controlHeightLG: 48,
      fontSize: 15,
      colorBgLayout,
      colorBgContainer,
      colorBgElevated: colorBgContainer,
      colorText,
      colorTextSecondary,
      colorTextTertiary: colorTextSecondary,
      colorTextDescription: colorTextSecondary,
      colorBorder,
      colorPrimary,
      colorLink,
      colorInfo: colorLink,
    },
  }
}
