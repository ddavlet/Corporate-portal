import { unstableSetRender } from 'antd'
import { createRoot, type Root } from 'react-dom/client'

/**
 * antd v5 static methods (Modal.confirm, message.*, notification.*) render through
 * rc-util, which looks for `createRoot` on the `react-dom` package. React 19 moved it
 * to `react-dom/client`, so without this hook static dialogs silently fail to open.
 * See https://u.ant.design/v5-for-19 — import this module once before rendering.
 */
unstableSetRender((node, container) => {
  const target = container as Element & { _reactRoot?: Root }
  target._reactRoot ||= createRoot(target)
  const root = target._reactRoot
  root.render(node)
  return async () => {
    await new Promise((resolve) => setTimeout(resolve, 0))
    root.unmount()
  }
})
