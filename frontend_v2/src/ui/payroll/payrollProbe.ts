export type PayrollProbeDecision = 'wait' | 'skip' | 'probe'

/**
 * Whether the cash page should ask payable-documents to decide on the payroll payout button.
 * With the payroll module off for the tenant the endpoint always answers 403, so it is not called.
 * An unknown catalog (null) keeps the old behaviour: the request itself decides.
 */
export function payrollProbeDecision(opts: {
  needExpenses: boolean
  catalogLoading: boolean
  payrollTenantEnabled: boolean | null
}): PayrollProbeDecision {
  if (!opts.needExpenses) return 'skip'
  if (opts.catalogLoading) return 'wait'
  if (opts.payrollTenantEnabled === false) return 'skip'
  return 'probe'
}
