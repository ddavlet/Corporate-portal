import type { ReactNode } from 'react'
import { Drawer } from 'antd'

export type MobileSheetProps = {
  open: boolean
  onClose: () => void
  title?: ReactNode
  /** Pinned under the content (actions of the sheet); the home indicator inset is added. */
  footer?: ReactNode
  children: ReactNode
  /** Keep the content mounted while closed (a form that must not lose what was typed). */
  keepMounted?: boolean
}

/**
 * Bottom sheet of the mobile layout: as tall as its content, at most 85 % of the screen, with the safe-area insets of
 * the installed app. Escape, the mask and the close button close it; focus stays inside while it is open.
 */
export function MobileSheet({ open, onClose, title, footer, children, keepMounted = false }: MobileSheetProps) {
  return (
    <Drawer
      open={open}
      onClose={onClose}
      title={title}
      footer={footer}
      placement="bottom"
      closable={{ 'aria-label': 'Закрыть' }}
      height="auto"
      rootClassName="m-sheet"
      destroyOnHidden={!keepMounted}
    >
      {children}
    </Drawer>
  )
}
