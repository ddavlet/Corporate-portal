/** WCAG 2 contrast of CSS colours for tests: `#rgb`, `#rrggbb`, `rgb()` and `rgba()` (blended over the background). */

type Rgba = [number, number, number, number]

function parseColor(value: string): Rgba {
  const v = value.trim().toLowerCase()
  if (v.startsWith('#')) {
    const hex = v.length === 4 ? [...v.slice(1)].map((c) => c + c).join('') : v.slice(1, 7)
    return [0, 2, 4].map((i) => parseInt(hex.slice(i, i + 2), 16)).concat(1) as Rgba
  }
  const m = v.match(/^rgba?\(([^)]+)\)$/)
  if (!m) throw new Error(`Unsupported colour: ${value}`)
  const parts = m[1].split(/[\s,/]+/).filter(Boolean).map(Number)
  return [parts[0], parts[1], parts[2], parts[3] ?? 1]
}

function blend(fg: Rgba, bg: Rgba): Rgba {
  const a = fg[3]
  return [0, 1, 2].map((i) => fg[i] * a + bg[i] * (1 - a)).concat(1) as Rgba
}

function luminance([r, g, b]: Rgba): number {
  const lin = [r, g, b].map((c) => {
    const s = c / 255
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4
  })
  return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
}

/** Contrast ratio of `foreground` over `background` (the background is first blended over white). */
export function contrastRatio(foreground: string, background = '#ffffff'): number {
  const bg = blend(parseColor(background), [255, 255, 255, 1])
  const fg = blend(parseColor(foreground), bg)
  const [hi, lo] = [luminance(fg), luminance(bg)].sort((a, b) => b - a)
  return (hi + 0.05) / (lo + 0.05)
}
