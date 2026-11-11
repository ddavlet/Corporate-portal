import { describe, expect, it } from 'vitest'
import { buildMobileMenu, findMobileMenuItem, findMobileSectionTitle } from './mobileMenu'

const names = (items: { name: string }[]) => items.map((item) => item.name)

describe('buildMobileMenu', () => {
  it('lists every section when all modules are available', () => {
    const menu = buildMobileMenu(() => true)
    expect(names(menu.main)).toEqual(['Заявки', 'Уведомления', 'Инвестиции'])
    expect(names(menu.desktop)).toEqual([
      'Задачи',
      'Касса',
      'Банк',
      'Корп. карта',
      'Начисления ЗП',
      'Отчёты',
      'Долги клиентов',
      'Бюджеты',
      'Договоры',
    ])
  })

  it('never offers «Панель», «Настройки» or «Админка»', () => {
    const menu = buildMobileMenu(() => true)
    const all = names([...menu.main, ...menu.desktop])
    for (const forbidden of ['Панель', 'Настройки', 'Админка']) expect(all).not.toContain(forbidden)
  })

  it('drops the sections of modules without access, keeps the ones without a module', () => {
    const menu = buildMobileMenu((key) => key === 'requests' || key === 'bank')
    expect(names(menu.main)).toEqual(['Заявки', 'Уведомления'])
    expect(names(menu.desktop)).toEqual(['Банк'])
  })

  it('keeps only «Уведомления» when no module is available', () => {
    const menu = buildMobileMenu(() => false)
    expect(names(menu.main)).toEqual(['Уведомления'])
    expect(menu.desktop).toEqual([])
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

  it('falls back to the menu item, and to nothing for unknown paths', () => {
    expect(findMobileSectionTitle('/cash/expenses/5')).toBe('Касса')
    expect(findMobileSectionTitle('/requests/12')).toBe('Заявки')
    expect(findMobileSectionTitle('/settingsx')).toBeNull()
  })
})
