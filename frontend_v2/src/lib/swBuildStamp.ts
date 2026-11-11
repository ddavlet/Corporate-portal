/**
 * Build stamp for the service worker.
 *
 * public/sw.js is copied into every build unchanged, and a browser installs a new worker only when the bytes of the
 * script differ. Without a stamp registration.update() after a deploy finds "the same" worker, controllerchange never
 * fires and a long-lived installed app stays on the old JS. The build appends one comment line with an id derived from
 * the bundle's hashed file names, so every build with different code ships a different sw.js.
 */

export const SW_BUILD_STAMP_PREFIX = '// kolberg-build: '

const STAMP_LINE = /\n?\/\/ kolberg-build: [^\n]*\n?$/

/** Returns the worker source with exactly one trailing build stamp (an older stamp is replaced). */
export function stampServiceWorker(source: string, buildId: string): string {
  const id = buildId.trim()
  if (!id || /\s/.test(id)) throw new Error(`Invalid service worker build id: "${buildId}"`)
  const body = source.replace(STAMP_LINE, '').replace(/\s+$/, '')
  return `${body}\n${SW_BUILD_STAMP_PREFIX}${id}\n`
}

/** The build id stamped into the worker source, or null when there is none. */
export function readServiceWorkerBuildId(source: string): string | null {
  const match = source.match(/\/\/ kolberg-build: (\S+)\s*$/)
  return match ? match[1] : null
}
