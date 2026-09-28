import { useEffect, useRef, useState } from 'react'

export function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function'
    ? window.matchMedia('(prefers-reduced-motion: reduce)').matches
    : false
}

/** Counts from the previous value to `target` (ease-out); the final value at once when motion is reduced. */
export function useCountUp(target: number, durationMs = 900): number {
  const [shown, setShown] = useState(() => (prefersReducedMotion() ? target : 0))
  const from = useRef(shown)
  useEffect(() => {
    if (prefersReducedMotion()) {
      from.current = target
      setShown(target)
      return
    }
    const start = performance.now()
    const origin = from.current
    let frame = 0
    const step = (now: number) => {
      const progress = Math.min(1, Math.max(0, (now - start) / durationMs))
      const eased = 1 - (1 - progress) ** 3
      const value = progress === 1 ? target : origin + (target - origin) * eased
      from.current = value
      setShown(value)
      if (progress < 1) frame = requestAnimationFrame(step)
    }
    frame = requestAnimationFrame(step)
    return () => cancelAnimationFrame(frame)
  }, [target, durationMs])
  return shown
}
