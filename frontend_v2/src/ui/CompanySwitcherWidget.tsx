import { useMemo } from 'react'
import { Badge, Select, Space, Typography } from 'antd'
import { useActionItems } from '../lib/useActionItems'
import { useCompany } from './company'

/**
 * Company picker in the header of the shared app host, with the "requires my action" count of each company.
 * Counts come from the live action items (all companies) and fall back to the list's counts until they load.
 * Renders nothing on a tenant subdomain.
 */
export function CompanySwitcherWidget({ compact = false }: { compact?: boolean }) {
  const { enabled, companies, current, switchCompany } = useCompany()
  const { items, loading, error } = useActionItems()

  const counts = useMemo(() => {
    const result = new Map<string, number>()
    if (loading || error) {
      companies.forEach((company) => result.set(company.subdomain, company.action_items_count))
      return result
    }
    items.forEach((item) => {
      const subdomain = item.tenant?.subdomain
      if (subdomain) result.set(subdomain, (result.get(subdomain) ?? 0) + 1)
    })
    return result
  }, [companies, items, loading, error])

  if (!enabled || companies.length === 0) return null

  return (
    <Select
      aria-label="Компания"
      value={current ?? undefined}
      onChange={(value: string) => switchCompany(value)}
      popupMatchSelectWidth={false}
      style={{ width: compact ? 132 : 200 }}
      labelRender={(option) => {
        const company = companies.find((c) => c.subdomain === option.value)
        return <span title={company?.name}>{company?.name ?? String(option.value ?? '')}</span>
      }}
      options={companies.map((company) => {
        const count = counts.get(company.subdomain) ?? 0
        return {
          value: company.subdomain,
          title: company.name,
          label: (
            <Space size={8} style={{ display: 'flex', justifyContent: 'space-between' }}>
              <Typography.Text style={{ maxWidth: 240 }} ellipsis>
                {company.name}
              </Typography.Text>
              {count > 0 ? (
                <Badge count={count} size="small" overflowCount={99} />
              ) : null}
            </Space>
          ),
        }
      })}
    />
  )
}
