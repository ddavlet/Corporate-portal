import type { ReactNode } from 'react'
import { ConfigProvider, theme, type GlobalToken } from 'antd'

export type MobileTextTone = 'success' | 'info' | 'error' | 'warning'

/**
 * Coloured text of the phone screens (status tags, decisions, error notes). The antd `color*TextHover` tokens are shade 5
 * of a palette and `colorWarningActive` is gold 7, all below 4.5:1 on white, so the text takes the preset palette shades
 * that pass on white and on the light tints of the same colour: green 8 (~5.4:1), blue 7 (~6.2:1), red 7 (~5.6:1),
 * orange 8 (~5.4:1).
 */
export function mobileToneTextColor(tone: MobileTextTone, token: GlobalToken): string {
  switch (tone) {
    case 'success':
      return token.green8
    case 'info':
      return token.blue7
    case 'error':
      return token.red7
    case 'warning':
      return token.orange8
  }
}

/**
 * Buttons of the phone card's action bar, sheets and comments: white text on the default primary (#1677ff, about 4.1:1)
 * and on the danger red (#ff4d4f, about 3.3:1) is below 4.5:1, so the fills take the darker «active» shades of the same
 * palette (about 6.2:1 and 4.6:1). Hover keeps the dark fill instead of lightening it. Small buttons get a 44 px target.
 * Secondary text (`Typography.Text type="secondary"`, colorTextDescription ≈ 3.4:1) takes colorTextSecondary (≈ 7:1),
 * links the darker primary.
 */
export function MobileActionsTheme({ children }: { children: ReactNode }) {
  const { token } = theme.useToken()
  return (
    <ConfigProvider
      theme={{
        token: {
          colorTextDescription: token.colorTextSecondary,
          colorLink: token.colorPrimaryActive,
          colorLinkHover: token.colorPrimaryActive,
        },
        components: {
          Button: {
            colorPrimary: token.colorPrimaryActive,
            colorPrimaryHover: token.colorPrimaryActive,
            colorError: token.colorErrorActive,
            colorErrorHover: token.colorErrorActive,
            controlHeightSM: 44,
          },
        },
      }}
    >
      {children}
    </ConfigProvider>
  )
}
