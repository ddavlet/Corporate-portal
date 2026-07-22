import { describe, expect, it } from 'vitest'
import { toPendingApprovals } from './adapters'
import type { MyApprovalGroup } from '../../../lib/api'

function makeGroup(overrides: Partial<MyApprovalGroup['request']> = {}): MyApprovalGroup {
  return {
    request: {
      id: 1,
      title: 'Заявка на оплату',
      description: 'Оплата аренды офиса за июль',
      amount: '1000',
      currency: 'UZS',
      status: '1',
      ...overrides,
    },
    approvals: [
      {
        id: 10,
        step: 1,
        step_type: 'serial',
        decision: 'pending',
      },
    ],
  }
}

describe('toPendingApprovals', () => {
  it('passes through the request description', () => {
    const [item] = toPendingApprovals([makeGroup()])
    expect(item.description).toBe('Оплата аренды офиса за июль')
  })

  it('returns null when description is missing', () => {
    const [item] = toPendingApprovals([makeGroup({ description: undefined })])
    expect(item.description).toBeNull()
  })
})
