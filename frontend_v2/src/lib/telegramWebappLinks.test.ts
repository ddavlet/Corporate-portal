import { describe, expect, it } from 'vitest'
import { tmeBotUsername, tmeLinkForeignBot, tmeLinkPrefix } from './telegramWebappLinks'

describe('telegramWebappLinks', () => {
  it('extracts bot username from t.me links', () => {
    expect(tmeBotUsername('https://t.me/acme_bot/comments')).toBe('acme_bot')
    expect(tmeBotUsername('t.me/acme_bot/comments')).toBe('acme_bot')
    expect(tmeBotUsername('https://telegram.me/acme_bot?startapp=x')).toBe('acme_bot')
    expect(tmeBotUsername('https://acme.example.com/tg')).toBeNull()
    expect(tmeBotUsername('')).toBeNull()
  })

  it('builds link prefix from tenant bot', () => {
    expect(tmeLinkPrefix('@acme_bot')).toBe('https://t.me/acme_bot/')
  })

  it('reports foreign bot only when it differs', () => {
    expect(tmeLinkForeignBot('https://t.me/other_bot/comments', 'acme_bot')).toBe('other_bot')
    expect(tmeLinkForeignBot('https://t.me/Acme_Bot/comments', '@acme_bot')).toBeNull()
    expect(tmeLinkForeignBot('https://acme.example.com/tg', 'acme_bot')).toBeNull()
    expect(tmeLinkForeignBot('https://t.me/other_bot/comments', '')).toBeNull()
  })
})
