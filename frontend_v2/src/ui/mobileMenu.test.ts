import { describe, expect, it } from 'vitest'
import { buildMobileMenu, findMobileMenuItem, findMobileSectionTitle } from './mobileMenu'

const names = (items: { name: string }[]) => items.map((item) => item.name)

describe('buildMobileMenu', () => {
  it('offers only «Заявки» and «Инвестиции» on the phone', () => {
    const menu = buildMobileMenu(() => true)
    expect(names(menu.main)).toEqual(['Заявки', 'Инвестиции'])
    expect(Object.keys(menu)).toEqual(['main'])
  })

  it('never offers «Панель», «Настройки», «Админка» or the desktop-only sections', () => {
    const all = names(buildMobileMenu(() => true).main)
    for (const forbidden of ['Панель', 'Настройки', 'Админка', 'Уведомления', 'Касса', 'Банк', 'Корп. карта', 'Начисления ЗП', 'Договоры']) {
      expect(all).not.toContain(forbidden)
    }
  })

  it('drops the sections of modules without access', () => {
    expect(names(buildMobileMenu((key) => key === 'requests').main)).toEqual(['Заявки'])
    expect(buildMobileMenu(() => false).main).toEqual([])
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
})
