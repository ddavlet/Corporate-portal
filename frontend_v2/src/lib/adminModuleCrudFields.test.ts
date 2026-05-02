import { describe, expect, it } from 'vitest'
import {
  planAdminCreateFieldsFromOptionsPost,
  planAdminCreateFieldsFromRow,
} from './adminModuleCrudFields'

describe('planAdminCreateFieldsFromRow', () => {
  it('builds empty initial values by primitive shapes and skips nested objects', () => {
    const plan = planAdminCreateFieldsFromRow({
      id: 1,
      tenant: 'x',
      name: 'A',
      amount: 100,
      enabled: false,
      note: null,
      meta: { x: 1 },
    })

    expect(plan.fields.map((f) => f.key).sort()).toEqual(['amount', 'enabled', 'name', 'note'])
    expect(plan.nonEditable.some((x) => x.key === 'meta')).toBe(true)
    expect(plan.initial.name).toBe('')
    expect(plan.initial.amount).toBe(undefined)
    expect(plan.initial.note).toBe(null)
    expect(plan.initial.enabled).toBe(false)
  })
})

describe('planAdminCreateFieldsFromOptionsPost', () => {
  it('maps DRF POST metadata primitives and skips read-only fields', () => {
    const plan = planAdminCreateFieldsFromOptionsPost({
      title: { type: 'string', required: true, read_only: false },
      hidden: { type: 'integer', required: false, read_only: true },
      amount: { type: 'decimal', required: false, read_only: false },
      skipped: { type: 'nested object', read_only: false },
    })

    expect(plan).not.toBeNull()
    expect(plan!.fields.map((f) => `${f.key}:${f.type}`).sort()).toEqual([
      'amount:number',
      'title:string',
    ])
    expect(plan!.initial.amount).toBe(undefined)
    expect(plan!.initial.title).toBe('')
  })

  it('maps choice lists', () => {
    const plan = planAdminCreateFieldsFromOptionsPost({
      status: {
        type: 'choice',
        required: false,
        read_only: false,
        choices: [
          { value: 'draft', display_name: 'Черновик' },
          { value: 'done', display_name: 'Готово' },
        ],
      },
    })

    expect(plan!.fields).toHaveLength(1)
    expect(plan!.fields[0].choices).toHaveLength(2)
    expect(plan!.fields[0].choices![1].label).toBe('Готово')
    expect(plan!.initial.status).toBe(undefined)
  })

  it('returns null for empty payloads', () => {
    expect(planAdminCreateFieldsFromOptionsPost(undefined)).toBeNull()
    expect(planAdminCreateFieldsFromOptionsPost({})).toBeNull()
  })
})
