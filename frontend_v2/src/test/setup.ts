import '@testing-library/jest-dom/vitest'
import '../lib/antdReact19'
import { Modal, message, notification } from 'antd'
import { afterAll, afterEach, vi } from 'vitest'
import { cleanup } from '@testing-library/react'
import { waitForQuietDocument } from './helpers'

afterEach(() => {
  cleanup()
})

// antd's static dialogs and toasts (Modal.confirm, message.*, notification.*) and its click waves render into React
// roots of their own (lib/antdReact19), which Testing Library's cleanup does not know, and they keep changing the page
// through timers and animation frames after a test ends. Close them after a file's last test and wait until the page is
// quiet: React work left for later runs after jsdom is torn down and fails the run with «window is not defined».
afterAll(async () => {
  vi.useRealTimers()
  Modal.destroyAll()
  // Only close toasts that are on screen: without one, antd would first create its toast holder.
  if (document.querySelector('.ant-message-notice')) message.destroy()
  if (document.querySelector('.ant-notification-notice')) notification.destroy()
  await waitForQuietDocument()
})

if (!window.matchMedia) {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: (query: string) => ({
      // Tests run as a viewer who asked for less motion: counters and transitions show final values at once.
      matches: query.includes('prefers-reduced-motion'),
      media: query,
      onchange: null,
      addListener: () => undefined,
      removeListener: () => undefined,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      dispatchEvent: () => false,
    }),
  })
}
