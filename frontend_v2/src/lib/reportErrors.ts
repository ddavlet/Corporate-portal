import { ApiError } from './api'

export const NETWORK_ERROR_MESSAGE = 'Нет связи с сервером. Проверьте интернет и повторите.'

/** Russian text for a failed report request: the server's message, a lost connection, or the fallback. */
export function describeReportError(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.message || fallback
  // fetch() rejects with a TypeError («Failed to fetch», «Load failed») when the connection is lost.
  if (error instanceof TypeError) return NETWORK_ERROR_MESSAGE
  return fallback
}
