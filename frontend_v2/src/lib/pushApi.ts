import { ApiError, apiFetch, parseErrorBody } from './api'

/**
 * Web Push subscription API (`/api/notifications/push/*`). The paths need no company: one subscription per device
 * carries the notifications of all the user's companies and is created only on the shared app host.
 * Endpoints and keys are never logged.
 */

export const PUSH_VAPID_KEY_URL = '/api/notifications/push/vapid-public-key/'
export const PUSH_SUBSCRIBE_URL = '/api/notifications/push/subscribe/'
export const PUSH_UNSUBSCRIBE_URL = '/api/notifications/push/unsubscribe/'

export type VapidPublicKey = { enabled: boolean; public_key: string | null }

export type PushSubscriptionPayload = {
  endpoint: string
  keys: { p256dh: string; auth: string }
}

type RequestOptions = {
  /**
   * Token to send when the portal tokens may already be gone (logout clears them right after the call starts).
   * apiFetch keeps an explicit Authorization header when it has no token of its own.
   */
  accessToken?: string | null
}

function jsonInit(body: unknown, options?: RequestOptions): RequestInit {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (options?.accessToken) headers.Authorization = `Bearer ${options.accessToken}`
  return { method: 'POST', headers, body: JSON.stringify(body) }
}

async function ensureOk(res: Response): Promise<void> {
  if (!res.ok) throw new ApiError(res.status, await parseErrorBody(res))
}

export async function getVapidPublicKey(): Promise<VapidPublicKey> {
  const res = await apiFetch(PUSH_VAPID_KEY_URL, {}, { silent: true })
  await ensureOk(res)
  const json = (await res.json().catch(() => null)) as Partial<VapidPublicKey> | null
  const key = typeof json?.public_key === 'string' && json.public_key.trim() ? json.public_key.trim() : null
  return { enabled: Boolean(json?.enabled) && Boolean(key), public_key: key }
}

/** Creates or re-binds the device subscription to the signed-in user (upsert by endpoint on the server). */
export async function postPushSubscription(payload: PushSubscriptionPayload): Promise<void> {
  const res = await apiFetch(PUSH_SUBSCRIBE_URL, jsonInit(payload), { silent: true })
  await ensureOk(res)
}

/** Revokes the device subscription on the server. A subscription the server does not know (404) counts as revoked. */
export async function postPushUnsubscribe(endpoint: string, options?: RequestOptions): Promise<void> {
  const res = await apiFetch(PUSH_UNSUBSCRIBE_URL, jsonInit({ endpoint }, options), {
    silent: true,
    treatAuthErrorsAsGlobal: false,
  })
  if (res.status === 404) return
  await ensureOk(res)
}
