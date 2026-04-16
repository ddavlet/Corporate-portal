export type ShellMenuRoute = {
  path: string
  name: string
  icon: JSX.Element
  moduleKey?: string
}

const INVESTOR_ALLOWED_PATHS = new Set<string>(['/', '/reports'])

export function filterInvestorMenuRoutes({
  isInvestor,
  path,
}: {
  isInvestor: boolean
  path: string
}): boolean {
  if (!isInvestor) return true
  return INVESTOR_ALLOWED_PATHS.has(path)
}
