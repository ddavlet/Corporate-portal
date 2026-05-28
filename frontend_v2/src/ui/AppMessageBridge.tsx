import { useEffect } from 'react'
import { App } from 'antd'
import { setAntdMessageApi } from '../lib/apiNotify'

/** Binds antd App message API for toasts from apiFetch and other non-React modules. */
export function AppMessageBridge() {
  const { message } = App.useApp()

  useEffect(() => {
    setAntdMessageApi(message)
    return () => setAntdMessageApi(null)
  }, [message])

  return null
}
