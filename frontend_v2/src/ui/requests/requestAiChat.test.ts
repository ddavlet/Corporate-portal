import { beforeEach, describe, expect, it, vi } from 'vitest'
import { closeRequestAiChat, ensureRequestAiChat, isRequestAiChatOpen } from './requestAiChat'

const MOUNT_ID = 'kolberg-request-ai-chat'

function mountChatDom(open: boolean) {
  document.body.innerHTML = `
    <div id="${MOUNT_ID}">
      <div class="chat-window-wrapper">
        <div class="chat-window" style="display: ${open ? 'block' : 'none'}"></div>
        <button type="button" class="chat-window-toggle">toggle</button>
        <button type="button" class="chat-close-button">close</button>
      </div>
    </div>
  `
}

describe('requestAiChat close', () => {
  beforeEach(() => {
    document.body.innerHTML = ''
  })

  it('isRequestAiChatOpen reflects chat-window visibility', () => {
    mountChatDom(true)
    expect(isRequestAiChatOpen()).toBe(true)
    const win = document.querySelector(`#${MOUNT_ID} .chat-window`) as HTMLElement
    win.style.display = 'none'
    expect(isRequestAiChatOpen()).toBe(false)
  })

  it('closeRequestAiChat clicks toggle when window is open', () => {
    mountChatDom(true)
    const toggle = document.querySelector<HTMLButtonElement>(`#${MOUNT_ID} .chat-window-toggle`)!
    const spy = vi.spyOn(toggle, 'click')
    closeRequestAiChat()
    expect(spy).toHaveBeenCalledTimes(1)
  })

  it('header close button triggers toggle (n8n "close" event is not handled)', () => {
    mountChatDom(true)
    ensureRequestAiChat()
    const toggle = document.querySelector<HTMLButtonElement>(`#${MOUNT_ID} .chat-window-toggle`)!
    const toggleSpy = vi.spyOn(toggle, 'click')
    document.querySelector<HTMLButtonElement>(`#${MOUNT_ID} .chat-close-button`)!.click()
    expect(toggleSpy).toHaveBeenCalled()
  })
})
