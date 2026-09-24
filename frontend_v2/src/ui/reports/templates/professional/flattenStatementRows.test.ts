import { describe, expect, it } from 'vitest'
import { defaultOpenGroups, flattenStatementRows } from './flattenStatementRows'
import { STATEMENT } from './testStatement'

const keys = (open: string[]) => flattenStatementRows(STATEMENT.rows, new Set(open)).map((d) => `${d.key}/${d.variant}`)

describe('flattenStatementRows', () => {
  it('opens top-level sections by default', () => {
    expect(defaultOpenGroups(STATEMENT.rows)).toEqual(['rev', 'opex'])
  })

  it('wraps an open section in a header and an «Итого» row, with nested groups closed', () => {
    expect(keys(['rev'])).toEqual([
      'rev:header/header',
      'rev.bank/item',
      'rev.cash/nested',
      'rev:total/total',
      'opex/collapsed',
      'ebit/result',
      'ebit_margin/ratio',
      'inv:spacer/spacer',
      'inv/item',
    ])
  })

  it('shows nested lines when the nested group is open', () => {
    expect(keys(['rev', 'rev.cash'])).toContain('rev.cash.a1b2c3d4/item')
  })

  it('collapses everything when nothing is open', () => {
    expect(keys([]).slice(0, 2)).toEqual(['rev/collapsed', 'opex/collapsed'])
  })
})
