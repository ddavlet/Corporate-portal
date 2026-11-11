import './lib/antdReact19'
import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { App as AntdApp, ConfigProvider } from 'antd'
import { AppMessageBridge } from './ui/AppMessageBridge'
import ruRU from 'antd/locale/ru_RU'
import dayjs from 'dayjs'
import 'dayjs/locale/ru'
import utc from 'dayjs/plugin/utc'
import timezone from 'dayjs/plugin/timezone'

dayjs.locale('ru')
dayjs.extend(utc)
dayjs.extend(timezone)
dayjs.tz.setDefault('Asia/Tashkent')
import { App } from './routes/App'
import { AuthProvider } from './ui/auth'
import { captureInstallPrompt, registerPortalServiceWorker } from './lib/pwa'
import { initPortalMode } from './lib/portalMode'
import 'antd/dist/reset.css'
import './styles.css'

void registerPortalServiceWorker()
// Chrome fires beforeinstallprompt early: listen before the first render (the banner reads it later).
captureInstallPrompt()

function renderApp() {
  ReactDOM.createRoot(document.getElementById('root')!).render(
    <React.StrictMode>
      <ConfigProvider locale={ruRU}>
        <AntdApp>
          <AppMessageBridge />
          <AuthProvider>
            <BrowserRouter basename="/app">
              <App />
            </BrowserRouter>
          </AuthProvider>
        </AntdApp>
      </ConfigProvider>
    </React.StrictMode>,
  )
}

// Subdomain or shared app host: decided before the first render (cached; see lib/portalMode.ts).
void initPortalMode().then(renderApp)

