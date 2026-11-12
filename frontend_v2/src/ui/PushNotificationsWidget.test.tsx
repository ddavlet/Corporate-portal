import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const { push } = vi.hoisted(() => ({
  push: {
    getPushSupport: vi.fn(),
    enablePush: vi.fn(),
    revokePushSubscription: vi.fn(),
    syncPushSubscription: vi.fn(),
  },
}))

vi.mock('../lib/webPush', () => push)
vi.mock('../lib/portalMode', () => ({ getSharedHost: () => 'app.kolberg.uz' }))

import { PushNotificationsWidget } from './PushNotificationsWidget'

async function renderWidget() {
  const view = render(<PushNotificationsWidget />)
  await waitFor(() => expect(push.getPushSupport).toHaveBeenCalled())
  return view
}

describe('PushNotificationsWidget', () => {
  beforeEach(() => {
    push.getPushSupport.mockReset().mockResolvedValue('default')
    push.enablePush.mockReset().mockResolvedValue('subscribed')
    push.revokePushSubscription.mockReset().mockResolvedValue(undefined)
    push.syncPushSubscription.mockReset().mockResolvedValue(false)
  })

  it('offers to enable notifications and asks for permission only on click', async () => {
    await renderWidget()
    const button = await screen.findByRole('button', { name: /Включить уведомления/ })
    expect(push.enablePush).not.toHaveBeenCalled()

    push.getPushSupport.mockResolvedValue('granted')
    push.syncPushSubscription.mockResolvedValue(true)
    await userEvent.click(button)

    expect(push.enablePush).toHaveBeenCalledTimes(1)
    expect(await screen.findByRole('button', { name: /Отключить уведомления/ })).toBeInTheDocument()
    expect(screen.getByText('Уведомления включены на этом устройстве.')).toBeInTheDocument()
  })

  it('shows the disable button when this device is subscribed, and disables on click', async () => {
    push.getPushSupport.mockResolvedValue('granted')
    push.syncPushSubscription.mockResolvedValue(true)
    await renderWidget()
    const button = await screen.findByRole('button', { name: /Отключить уведомления/ })

    push.syncPushSubscription.mockResolvedValue(false)
    await userEvent.click(button)

    expect(push.revokePushSubscription).toHaveBeenCalledTimes(1)
    expect(await screen.findByRole('button', { name: /Включить уведомления/ })).toBeInTheDocument()
  })

  it('offers to enable when permission is granted but the device has no subscription', async () => {
    push.getPushSupport.mockResolvedValue('granted')
    await renderWidget()
    expect(await screen.findByRole('button', { name: /Включить уведомления/ })).toBeInTheDocument()
  })

  it('reports a failed attempt and keeps the button', async () => {
    push.enablePush.mockResolvedValue('error')
    await renderWidget()
    await userEvent.click(await screen.findByRole('button', { name: /Включить уведомления/ }))
    expect(await screen.findByText('Не удалось включить уведомления. Попробуйте ещё раз.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Включить уведомления/ })).toBeInTheDocument()
  })

  it('reports that push is unavailable when enabling cannot finish (no server key or service worker)', async () => {
    push.enablePush.mockResolvedValue('unavailable')
    push.getPushSupport.mockResolvedValue('granted')
    await renderWidget()
    await userEvent.click(await screen.findByRole('button', { name: /Включить уведомления/ }))
    expect(
      await screen.findByText('Не удалось включить уведомления: сервис сейчас недоступен. Попробуйте позже.'),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Включить уведомления/ })).toBeInTheDocument()
  })

  it('reports a failed disable when the device is still subscribed', async () => {
    push.getPushSupport.mockResolvedValue('granted')
    push.syncPushSubscription.mockResolvedValue(true)
    await renderWidget()
    await userEvent.click(await screen.findByRole('button', { name: /Отключить уведомления/ }))
    expect(push.revokePushSubscription).toHaveBeenCalledTimes(1)
    expect(await screen.findByText('Не удалось отключить уведомления. Попробуйте ещё раз.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Отключить уведомления/ })).toBeInTheDocument()
  })

  it('reserves its place while support is being checked', async () => {
    let resolve: (value: string) => void = () => {}
    push.getPushSupport.mockReturnValue(new Promise((r) => (resolve = r)))
    const { container } = render(<PushNotificationsWidget />)
    expect(container.querySelector('[data-push-loading]')).toBeInTheDocument()
    resolve('default')
    expect(await screen.findByRole('button', { name: /Включить уведомления/ })).toBeInTheDocument()
    expect(container.querySelector('[data-push-loading]')).not.toBeInTheDocument()
  })

  it('shows the denied reason after the user blocks the prompt', async () => {
    push.enablePush.mockResolvedValue('denied')
    await renderWidget()
    push.getPushSupport.mockResolvedValue('denied')
    await userEvent.click(await screen.findByRole('button', { name: /Включить уведомления/ }))
    expect(await screen.findByText(/Уведомления запрещены в настройках браузера/)).toBeInTheDocument()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('points a company subdomain to the shared app', async () => {
    push.getPushSupport.mockResolvedValue('subdomain-use-shared-host')
    await renderWidget()
    const link = await screen.findByRole('link', { name: 'app.kolberg.uz' })
    expect(link).toHaveAttribute('href', 'https://app.kolberg.uz/app/notifications')
    expect(screen.getByRole('region', { name: 'Push-уведомления' })).toHaveTextContent(
      'Уведомления доступны в приложении по адресу app.kolberg.uz',
    )
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('tells iPhone users to add the portal to the Home Screen', async () => {
    push.getPushSupport.mockResolvedValue('ios-needs-install')
    await renderWidget()
    expect(await screen.findByText(/«Поделиться» → «На экран „Домой“»/)).toBeInTheDocument()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it.each([
    ['unsupported', 'Этот браузер не поддерживает push-уведомления.'],
    ['disabled-server', 'Push-уведомления сейчас недоступны.'],
  ])('explains why push is unavailable (%s, crit. 18)', async (support, text) => {
    push.getPushSupport.mockResolvedValue(support)
    await renderWidget()
    expect(await screen.findByText(text)).toBeInTheDocument()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('renders nothing in the Telegram Mini App', async () => {
    push.getPushSupport.mockResolvedValue('telegram')
    const { container } = await renderWidget()
    await waitFor(() => expect(push.getPushSupport).toHaveBeenCalledTimes(1))
    expect(container).toBeEmptyDOMElement()
  })
})
