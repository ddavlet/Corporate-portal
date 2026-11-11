import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { installViewport, setViewport } from '../test/viewport'

const pwa = vi.hoisted(() => ({
  canPrompt: false,
  ios: false,
  standalone: false,
  dismissed: false,
  promptInstall: vi.fn(),
  dismissInstallPrompt: vi.fn(),
}))

vi.mock('../lib/pwa', () => ({
  canPromptInstall: () => pwa.canPrompt,
  subscribeInstallPrompt: () => () => undefined,
  isIosSafari: () => pwa.ios,
  isStandaloneDisplay: () => pwa.standalone,
  isInstallPromptDismissed: () => pwa.dismissed,
  isTelegramWebAppContext: () => window.location.pathname.includes('/tg/'),
  promptInstall: () => pwa.promptInstall(),
  dismissInstallPrompt: () => pwa.dismissInstallPrompt(),
}))

import { InstallAppPromptWidget } from './InstallAppPromptWidget'

installViewport('phone')

describe('InstallAppPromptWidget', () => {
  beforeEach(() => {
    pwa.canPrompt = false
    pwa.ios = false
    pwa.standalone = false
    pwa.dismissed = false
    pwa.promptInstall.mockReset()
    pwa.promptInstall.mockResolvedValue('accepted')
    pwa.dismissInstallPrompt.mockReset()
    window.history.replaceState(null, '', '/app/requests')
  })

  afterEach(() => {
    window.history.replaceState(null, '', '/')
  })

  it('offers the browser install on Android', async () => {
    pwa.canPrompt = true
    render(<InstallAppPromptWidget />)
    expect(screen.getByRole('region', { name: 'Установить приложение' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Установить' }))
    await waitFor(() => expect(pwa.promptInstall).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(screen.queryByTestId('install-app-prompt')).toBeNull())
  })

  it('explains «Поделиться → На экран Домой» on iOS', () => {
    pwa.ios = true
    render(<InstallAppPromptWidget />)
    expect(screen.getByText(/«Поделиться», затем «На экран Домой»/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Установить' })).toBeNull()
  })

  it('remembers the close on the device', () => {
    pwa.ios = true
    render(<InstallAppPromptWidget />)
    fireEvent.click(screen.getByRole('button', { name: 'Закрыть подсказку' }))
    expect(pwa.dismissInstallPrompt).toHaveBeenCalledTimes(1)
    expect(screen.queryByTestId('install-app-prompt')).toBeNull()
  })

  it('stays hidden once closed earlier', () => {
    pwa.canPrompt = true
    pwa.dismissed = true
    render(<InstallAppPromptWidget />)
    expect(screen.queryByTestId('install-app-prompt')).toBeNull()
  })

  it('is not shown in the installed app', () => {
    pwa.canPrompt = true
    pwa.ios = true
    pwa.standalone = true
    render(<InstallAppPromptWidget />)
    expect(screen.queryByTestId('install-app-prompt')).toBeNull()
  })

  it('is not shown in the Telegram Mini App', () => {
    pwa.canPrompt = true
    window.history.replaceState(null, '', '/app/tg/requests')
    render(<InstallAppPromptWidget />)
    expect(screen.queryByTestId('install-app-prompt')).toBeNull()
  })

  it('is not shown on a desktop', () => {
    setViewport('desktop')
    pwa.canPrompt = true
    render(<InstallAppPromptWidget />)
    expect(screen.queryByTestId('install-app-prompt')).toBeNull()
  })

  it('is not shown where the browser cannot install', () => {
    render(<InstallAppPromptWidget />)
    expect(screen.queryByTestId('install-app-prompt')).toBeNull()
  })
})
