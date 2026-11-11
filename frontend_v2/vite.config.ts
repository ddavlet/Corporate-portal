import { createHash } from 'node:crypto'
import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { defineConfig, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import { stampServiceWorker } from './src/lib/swBuildStamp'

/**
 * Stamps dist/sw.js with a per-build id (see src/lib/swBuildStamp.ts). The id is a hash of the bundle's file names:
 * they carry content hashes, so the stamp changes exactly when the shipped code changes.
 */
function serviceWorkerBuildStamp(): Plugin {
  let outDir = ''
  let buildId = ''
  return {
    name: 'kolberg-sw-build-stamp',
    apply: 'build',
    configResolved(config) {
      outDir = resolve(config.root, config.build.outDir)
    },
    generateBundle(_options, bundle) {
      const names = Object.keys(bundle).sort().join('\n')
      buildId = createHash('sha256').update(names).digest('hex').slice(0, 16)
    },
    closeBundle() {
      // No bundle was generated (the build failed earlier): nothing to stamp, keep the original error visible.
      if (!buildId) return
      const file = resolve(outDir, 'sw.js')
      if (!existsSync(file)) throw new Error(`Service worker build stamp: ${file} is missing`)
      writeFileSync(file, stampServiceWorker(readFileSync(file, 'utf8'), buildId))
    },
  }
}

export default defineConfig({
  base: '/app/',
  plugins: [react(), serviceWorkerBuildStamp()],
  server: {
    strictPort: true,
  },
  test: {
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    clearMocks: true,
    restoreMocks: true,
  },
})
