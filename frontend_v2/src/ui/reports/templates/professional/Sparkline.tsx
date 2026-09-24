export function Sparkline({ values }: { values: (string | null)[] }) {
  const points = values.map((value) => Number(value ?? 0))
  if (points.length < 2) return null
  const min = Math.min(...points)
  const range = Math.max(...points) - min || 1
  const x = (index: number) => (index / (points.length - 1)) * 100
  const y = (value: number) => 30 - ((value - min) / range) * 26
  const line = points.map((value, index) => `${x(index).toFixed(2)},${y(value).toFixed(2)}`).join(' ')
  return (
    <svg className="rp-spark" viewBox="0 0 100 32" preserveAspectRatio="none" aria-hidden="true">
      <polygon className="rp-spark-area" points={`0,32 ${line} 100,32`} />
      <polyline className="rp-spark-line" points={line} vectorEffect="non-scaling-stroke" />
    </svg>
  )
}
