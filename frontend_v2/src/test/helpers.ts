import { vi } from 'vitest'

export type MockStorage = Storage

export function createStorageMock(): MockStorage {
  const data = new Map<string, string>()
  return {
    get length() {
      return data.size
    },
    key: vi.fn((index: number) => Array.from(data.keys())[index] ?? null),
    getItem: vi.fn((key: string) => data.get(key) ?? null),
    setItem: vi.fn((key: string, value: string) => {
      data.set(key, value)
    }),
    removeItem: vi.fn((key: string) => {
      data.delete(key)
    }),
    clear: vi.fn(() => {
      data.clear()
    }),
  }
}

export function createJsonResponse(status: number, payload: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
  } as Response
}

export function setWindowLocation(pathname = '/', search = '') {
  Object.defineProperty(globalThis, 'window', {
    value: { location: new URL(`https://example.com${pathname}${search}`) },
    configurable: true,
  })
}
