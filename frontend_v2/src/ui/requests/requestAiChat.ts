import '@n8n/chat/style.css'
import './requestAiChatTheme.css'
import { createChat } from '@n8n/chat'
import { getAuthAccessToken, getRequestAiChatWebhookUrl } from '../../lib/requestAiChat'

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

function buildChatOptions(webhookUrl: string) {
  const access = getAuthAccessToken()
  const headers: Record<string, string> = {}
  if (access) headers.Authorization = `Bearer ${access}`

  return {
    webhookUrl,
    target: `#${MOUNT_ID}`,
    mode: 'window' as const,
    loadPreviousSession: true,
    showWelcomeScreen: false,
    initialMessages: [
      'Здравствуйте! Помогу оформить заявку на оплату.',
      'Опишите поставщика, сумму, назначение платежа и срочность — уточню недостающие поля.',
    ],
    webhookConfig: {
      method: 'POST' as const,
      headers,
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

export async function ensureRequestAiChat(): Promise<void> {
  if (typeof document === 'undefined') return
  ensureMountElement()
  if (document.querySelector(`#${MOUNT_ID} .chat-window-wrapper`)) return

  const webhookUrl = await getRequestAiChatWebhookUrl()
  createChat(buildChatOptions(webhookUrl))
}

export async function openRequestAiChat(): Promise<void> {
  if (typeof document === 'undefined') return
  await ensureRequestAiChat()

  const toggle =
    document.querySelector<HTMLButtonElement>(`#${MOUNT_ID} .chat-window-toggle`) ??
    document.querySelector<HTMLButtonElement>('.chat-window-toggle')

  toggle?.click()
}
