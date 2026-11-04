import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const getMock = vi.fn()

vi.mock('../../lib/api', () => ({
  getTelegramBotSetup: () => getMock(),
}))

import { TelegramBotSetupWidget } from './TelegramBotSetupWidget'

const checklist = {
  bot_username: 'acme_bot',
  has_bot_token: true,
  main_app_url: 'https://acme.kolberg.uz/app/tg/',
  launch_mode: 'fullscreen',
  direct_links: [
    { short_name: 'payment', web_app_url: 'https://acme.kolberg.uz/app/tg/payment', link: 'https://t.me/acme_bot/payment' },
    { short_name: 'portal', web_app_url: 'https://acme.kolberg.uz/app/tg/', link: 'https://t.me/acme_bot/portal' },
  ],
  auto_synced: ['commands', 'description', 'menu_button'],
}

describe('TelegramBotSetupWidget', () => {
  beforeEach(() => {
    getMock.mockReset()
  })

  it('renders links from checklist', async () => {
    getMock.mockResolvedValue(checklist)
    render(<TelegramBotSetupWidget />)
    await waitFor(() => expect(screen.getByText('https://t.me/acme_bot/payment')).toBeTruthy())
    expect(screen.getByText('https://acme.kolberg.uz/app/tg/payment')).toBeTruthy()
    expect(screen.queryByText(/Укажите токен и username бота/)).toBeNull()
  })

  it('warns when bot username missing', async () => {
    getMock.mockResolvedValue({
      ...checklist,
      bot_username: '',
      direct_links: checklist.direct_links.map((d) => ({ ...d, link: '' })),
    })
    render(<TelegramBotSetupWidget />)
    await waitFor(() => expect(screen.getByText(/Укажите токен и username бота/)).toBeTruthy())
  })
})
