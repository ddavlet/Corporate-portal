import { message } from 'antd'
import type { MessageInstance } from 'antd/es/message/interface'

const NETWORK_ERROR = 'Не удалось связаться с сервером. Проверьте сеть и повторите попытку.'

let messageApi: MessageInstance | null = null

export function setAntdMessageApi(api: MessageInstance | null): void {
  messageApi = api
}

function getMessageApi(): MessageInstance {
  return messageApi ?? message
}

export function notifyApiError(text: string, duration = 5): void {
  const normalized = text.trim() || 'Произошла ошибка'
  getMessageApi().error(normalized, duration)
}

export function notifyApiSuccess(text: string, duration = 3): void {
  getMessageApi().success(text, duration)
}

export function notifyNetworkError(): void {
  notifyApiError(NETWORK_ERROR)
}
