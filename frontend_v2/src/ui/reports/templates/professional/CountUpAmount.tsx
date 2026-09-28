import { useCountUp } from './useCountUp'

/** A money figure that counts up to its value; `format` turns the plain number into page units. */
export function CountUpAmount({ value, format }: { value: string | null | undefined; format: (value: string) => string }) {
  const target = value === null || value === undefined || value === '' ? null : Number(value)
  const valid = target !== null && Number.isFinite(target)
  const shown = useCountUp(valid ? target : 0)
  if (!valid) return <>—</>
  return <>{format(String(Math.round(shown * 100) / 100))}</>
}
