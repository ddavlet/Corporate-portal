import { message } from 'antd'

const NETWORK_ERROR = 'Не удалось связаться с сервером. Проверьте сеть и повторите попытку.'

export function notifyApiError(text: string, duration = 5): void {
  const normalized = text.trim() || 'Произошла ошибка'
  message.error(normalized, duration)
}

export function notifyApiSuccess(text: string, duration = 3): void {
  message.success(text, duration)
}

export function notifyNetworkError(): void {
  notifyApiError(NETWORK_ERROR)
}
