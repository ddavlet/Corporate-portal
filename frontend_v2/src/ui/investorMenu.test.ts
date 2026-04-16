import { describe, expect, it } from 'vitest'

import { filterInvestorMenuRoutes } from './investorMenu'

describe('filterInvestorMenuRoutes', () => {
  it('allows any path for non-investor users', () => {
    expect(filterInvestorMenuRoutes({ isInvestor: false, path: '/' })).toBe(true)
    expect(filterInvestorMenuRoutes({ isInvestor: false, path: '/requests' })).toBe(true)
    expect(filterInvestorMenuRoutes({ isInvestor: false, path: '/settings' })).toBe(true)
  })

  it('allows only dashboard and reports for investors', () => {
    expect(filterInvestorMenuRoutes({ isInvestor: true, path: '/' })).toBe(true)
    expect(filterInvestorMenuRoutes({ isInvestor: true, path: '/reports' })).toBe(true)
    expect(filterInvestorMenuRoutes({ isInvestor: true, path: '/requests' })).toBe(false)
    expect(filterInvestorMenuRoutes({ isInvestor: true, path: '/admin' })).toBe(false)
  })
})
