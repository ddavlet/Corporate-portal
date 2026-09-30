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

/**
 * Resolves once the document has not changed for `quietMs`, or after `limitMs` at the latest. React commits change the
 * page, so a quiet page means the work a test left running (closing dialogs, animation steps) has finished.
 */
export function waitForQuietDocument(quietMs = 50, limitMs = 2000): Promise<void> {
  return new Promise((resolve) => {
    let quietTimer = setTimeout(done, quietMs)
    const limitTimer = setTimeout(done, limitMs)
    const observer = new MutationObserver(() => {
      clearTimeout(quietTimer)
      quietTimer = setTimeout(done, quietMs)
    })
    observer.observe(document, { subtree: true, childList: true, attributes: true, characterData: true })

    function done() {
      observer.disconnect()
      clearTimeout(quietTimer)
      clearTimeout(limitTimer)
      resolve()
    }
  })
}

/** Runs `check` as in a browser that refuses session storage (private mode, blocked site data): reading it throws. */
export async function withoutSessionStorage(check: () => void | Promise<void>): Promise<void> {
  const original = Object.getOwnPropertyDescriptor(globalThis, 'sessionStorage')
  Object.defineProperty(globalThis, 'sessionStorage', {
    configurable: true,
    get: () => {
      throw new DOMException('denied', 'SecurityError')
    },
  })
  try {
    await check()
  } finally {
    if (original) Object.defineProperty(globalThis, 'sessionStorage', original)
    else delete (globalThis as { sessionStorage?: Storage }).sessionStorage
  }
}

export function createJsonResponse(status: number, payload: unknown): Response {
  const base = {
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
    clone: () => createJsonResponse(status, payload),
  }
  return base as Response
}

export function setWindowLocation(pathname = '/', search = '') {
  Object.defineProperty(globalThis, 'window', {
    value: { location: new URL(`https://example.com${pathname}${search}`) },
    configurable: true,
  })
}
