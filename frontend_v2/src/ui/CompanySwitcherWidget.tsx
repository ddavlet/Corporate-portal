import { useMemo } from 'react'
import { Badge, Select, Space, Typography } from 'antd'
import { useActionItems } from '../lib/useActionItems'
import { useCompany } from './company'

type Props = {
  compact?: boolean
  /** `mobile`: fits the 360 px phone header (flexible width up to 160 px) and shows the other companies' count. */
  variant?: 'default' | 'mobile'
  /** Controlled dropdown (the mobile shell opens it from «В других компаниях ещё N»). */
  open?: boolean
  onOpenChange?: (open: boolean) => void
}

/**
 * Company picker in the header of the shared app host, with the "requires my action" count of each company.
 * Counts come from the live action items (all companies) and fall back to the list's counts until they load.
 * Renders nothing on a tenant subdomain.
 */
export function CompanySwitcherWidget({ compact = false, variant = 'default', open, onOpenChange }: Props) {
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

  const mobile = variant === 'mobile'
  const select = (
    <Select
      aria-label={mobile ? mobileLabel(otherCompaniesCount(counts, current)) : 'Компания'}
      value={current ?? undefined}
      onChange={(value: string) => switchCompany(value)}
      popupMatchSelectWidth={false}
      {...(open === undefined ? {} : { open })}
      {...(onOpenChange ? { onOpenChange } : {})}
      style={mobile ? { width: '100%' } : { width: compact ? 132 : 200 }}
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

  if (!mobile) return select

  // The closed switcher carries the count of the other companies: the current one is in the menu and the bell.
  return (
    <Badge
      className="m-company-switcher"
      count={otherCompaniesCount(counts, current)}
      size="small"
      overflowCount={99}
      offset={[-4, 4]}
      data-testid="company-switcher-other-badge"
    >
      {select}
    </Badge>
  )
}

/** Sum of the "requires my action" counts of every company except the current one. */
export function otherCompaniesCount(counts: Map<string, number>, current: string | null): number {
  let total = 0
  counts.forEach((count, subdomain) => {
    if (subdomain !== current) total += count
  })
  return total
}

function mobileLabel(others: number): string {
  return others > 0 ? `Компания (в других компаниях ждут действия: ${others})` : 'Компания'
}
