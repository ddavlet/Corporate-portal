/** Совпадает с `TenantUserRole` на бекенде. */
export const TENANT_ROLE_OPTIONS: Array<{ value: string; label: string }> = [
  { value: 'admin', label: 'Администратор компании' },
  { value: 'director', label: 'Директор' },
  { value: 'approver', label: 'Согласующий' },
  { value: 'requester', label: 'Заявитель' },
  { value: 'cashier', label: 'Кассир' },
  { value: 'accountant', label: 'Бухгалтер' },
  { value: 'investor', label: 'Инвестор' },
]

const ROLE_LABEL_BY_VALUE = new Map(TENANT_ROLE_OPTIONS.map((o) => [o.value, o.label]))

export function tenantRoleLabel(role: string): string {
  return ROLE_LABEL_BY_VALUE.get(role) ?? role
}
