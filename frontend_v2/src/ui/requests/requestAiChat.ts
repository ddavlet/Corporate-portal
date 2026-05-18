import '@n8n/chat/style.css'
import './requestAiChatTheme.css'
import { createChat } from '@n8n/chat'
import { getRequestAiChatWebhookUrl, hookRequestAiChatFetch } from '../../lib/requestAiChat'

hookRequestAiChatFetch()

const MOUNT_ID = 'kolberg-request-ai-chat'

function chatSource(): 'telegram' | 'portal' {
  return typeof window !== 'undefined' && window.location.pathname.includes('/tg/') ? 'telegram' : 'portal'
}

function ensureMountElement(): HTMLElement {
  let mount = document.getElementById(MOUNT_ID)
  if (!mount) {
    mount = document.createElement('div')
    mount.id = MOUNT_ID
    document.body.appendChild(mount)
  }
  return mount
}

function buildChatOptions() {
  return {
    webhookUrl: getRequestAiChatWebhookUrl(),
    target: `#${MOUNT_ID}`,
    mode: 'window' as const,
    showWindowCloseButton: true,
    loadPreviousSession: true,
    showWelcomeScreen: false,
    initialMessages: [
      'Здравствуйте! Помогу оформить заявку на оплату.',
      'Опишите поставщика, сумму, назначение платежа и срочность — уточню недостающие поля.',
    ],
    webhookConfig: {
      method: 'POST' as const,
    },
    metadata: {
      source: chatSource(),
    },
    defaultLanguage: 'en' as const,
    i18n: {
      en: {
        title: 'Заявка с ИИ',
        subtitle: 'Бета — диалог для создания заявки',
        footer: '',
        getStarted: 'Новый диалог',
        inputPlaceholder: 'Опишите заявку…',
        closeButtonTooltip: 'Закрыть',
      },
    },
  }
}

export function ensureRequestAiChat(): void {
  if (typeof document === 'undefined') return
  ensureMountElement()
  if (document.querySelector(`#${MOUNT_ID} .chat-window-wrapper`)) return
  createChat(buildChatOptions())
}

function isRequestAiChatOpen(): boolean {
  const win = document.querySelector(`#${MOUNT_ID} .chat-window`)
  if (!win) return false
  const style = window.getComputedStyle(win)
  return style.display !== 'none' && style.opacity !== '0' && style.visibility !== 'hidden'
}

export function closeRequestAiChat(): void {
  if (typeof document === 'undefined') return
  document.querySelector<HTMLButtonElement>(`#${MOUNT_ID} .chat-close-button`)?.click()
}

export function openRequestAiChat(): void {
  if (typeof document === 'undefined') return
  ensureRequestAiChat()
  if (isRequestAiChatOpen()) {
    closeRequestAiChat()
    return
  }
  document.querySelector<HTMLButtonElement>(`#${MOUNT_ID} .chat-window-toggle`)?.click()
}
