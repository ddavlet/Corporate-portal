import { describe, expect, it } from 'vitest'
import { payrollProbeDecision } from './payrollProbe'

describe('payrollProbeDecision', () => {
  it('skips the request when payroll is off for the tenant (no 403 in the network)', () => {
    expect(payrollProbeDecision({ needExpenses: true, catalogLoading: false, payrollTenantEnabled: false })).toBe('skip')
  })

  it('probes when payroll is on for the tenant', () => {
    expect(payrollProbeDecision({ needExpenses: true, catalogLoading: false, payrollTenantEnabled: true })).toBe('probe')
  })

  it('waits for the module catalog before deciding', () => {
    expect(payrollProbeDecision({ needExpenses: true, catalogLoading: true, payrollTenantEnabled: null })).toBe('wait')
  })

  it('falls back to probing when the catalog is unavailable', () => {
    expect(payrollProbeDecision({ needExpenses: true, catalogLoading: false, payrollTenantEnabled: null })).toBe('probe')
  })

  it('skips on the revenues-only view', () => {
    expect(payrollProbeDecision({ needExpenses: false, catalogLoading: false, payrollTenantEnabled: true })).toBe('skip')
  })
})
