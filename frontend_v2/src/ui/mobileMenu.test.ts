import { describe, expect, it } from 'vitest'
import { buildMobileMenu, findMobileMenuItem, findMobileSectionTitle } from './mobileMenu'

const names = (items: { name: string }[]) => items.map((item) => item.name)

describe('buildMobileMenu', () => {
  it('offers only «Заявки», «Инвестиции» and «Касса» on the phone', () => {
    const menu = buildMobileMenu(() => true)
    expect(names(menu.main)).toEqual(['Заявки', 'Инвестиции', 'Касса'])
    expect(Object.keys(menu)).toEqual(['main'])
  })

  it('never offers «Панель», «Настройки», «Админка» or the desktop-only sections', () => {
    const all = names(buildMobileMenu(() => true).main)
    for (const forbidden of ['Панель', 'Настройки', 'Админка', 'Уведомления', 'Банк', 'Корп. карта', 'Начисления ЗП', 'Договоры']) {
      expect(all).not.toContain(forbidden)
    }
  })

  it('drops the sections of modules without access', () => {
    expect(names(buildMobileMenu((key) => key === 'requests').main)).toEqual(['Заявки'])
    expect(buildMobileMenu(() => false).main).toEqual([])
  })

  it('offers «Касса» only with access to the cash module', () => {
    expect(names(buildMobileMenu((key) => key === 'cash').main)).toEqual(['Касса'])
    expect(names(buildMobileMenu((key) => key !== 'cash').main)).toEqual(['Заявки', 'Инвестиции'])
  })
})

describe('findMobileMenuItem', () => {
  it('matches the exact path and nested paths', () => {
    expect(findMobileMenuItem('/requests')?.name).toBe('Заявки')
    expect(findMobileMenuItem('/requests/12')?.name).toBe('Заявки')
    expect(findMobileMenuItem('/cash/5/edit')?.name).toBe('Касса')
  })

  it('does not match a path that only shares a prefix', () => {
    expect(findMobileMenuItem('/requests-archive')).toBeNull()
    expect(findMobileMenuItem('/bankruptcy')).toBeNull()
  })

  it('returns null for unknown paths', () => {
    expect(findMobileMenuItem('/')).toBeNull()
    expect(findMobileMenuItem('/settings')).toBeNull()
  })
})

describe('findMobileSectionTitle', () => {
  it('names the sections outside the menu', () => {
    expect(findMobileSectionTitle('/settings')).toBe('Настройки')
    expect(findMobileSectionTitle('/settings/users-roles')).toBe('Настройки')
    expect(findMobileSectionTitle('/admin')).toBe('Админка')
    expect(findMobileSectionTitle('/requests/audit')).toBe('Аудит месяцев')
    expect(findMobileSectionTitle('/requests/auto-config')).toBe('Автозаявки')
  })

  it('still names «Уведомления» and the desktop-only sections opened by a link', () => {
    expect(findMobileSectionTitle('/notifications')).toBe('Уведомления')
    expect(findMobileSectionTitle('/bank')).toBe('Банк')
  })

  it('falls back to the menu item, and to nothing for unknown paths', () => {
    expect(findMobileSectionTitle('/cash/expenses/5')).toBe('Касса')
    expect(findMobileSectionTitle('/requests/12')).toBe('Заявки')
    expect(findMobileSectionTitle('/settingsx')).toBeNull()
  })

  it('names the phone cash transfer form «Касса»', () => {
    expect(findMobileSectionTitle('/cash')).toBe('Касса')
    expect(findMobileSectionTitle('/cash/transfer')).toBe('Касса')
  })

  it('names the phone investments forms «Инвестиции»', () => {
    expect(findMobileSectionTitle('/investments/collect')).toBe('Инвестиции')
    expect(findMobileSectionTitle('/investments/returns/new')).toBe('Инвестиции')
  })
})
