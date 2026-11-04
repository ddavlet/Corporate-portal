import { useEffect, useState } from 'react'
import { Alert, Space, Spin, Typography } from 'antd'
import { getTelegramBotSetup, type TelegramBotSetupChecklist } from '../../lib/api'

const { Text } = Typography

function CopyValue({ value, hint }: { value: string; hint?: string }) {
  if (!value) {
    return <Text type="secondary">—{hint ? ` (${hint})` : ''}</Text>
  }
  return (
    <Text code copyable>
      {value}
    </Text>
  )
}

/** `reloadKey` changes after the tenant settings are (re)loaded, so saved token/username show up. */
export function TelegramBotSetupWidget({ reloadKey = 0 }: { reloadKey?: number }) {
  const [data, setData] = useState<TelegramBotSetupChecklist | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError('')
    getTelegramBotSetup()
      .then((res) => {
        if (!cancelled) setData(res)
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Не удалось загрузить чек-лист')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [reloadKey])

  const bot = data?.bot_username ? `@${data.bot_username}` : '@<бот>'
  const noBaseDomain = 'BASE_DOMAIN не настроен'

  return (
    <Space direction="vertical" size={8} style={{ display: 'flex' }} data-testid="telegram-bot-setup">
      <Text strong>Настройка бота в BotFather</Text>
      {loading ? <Spin size="small" /> : null}
      {error ? <Alert type="error" showIcon message={error} /> : null}
      {data ? (
        <>
          {!data.has_bot_token || !data.bot_username ? (
            <Alert type="warning" showIcon message="Укажите токен и username бота выше — без них ссылки не строятся." />
          ) : null}

          <div>
            <Text strong>1. Main App</Text>
            <div>
              <Text type="secondary">BotFather → /mybots → {bot} → Bot Settings → Configure Mini App</Text>
            </div>
            <div>
              URL: <CopyValue value={data.main_app_url} hint={noBaseDomain} />
            </div>
            <div>
              Launch mode: <Text strong>Fullscreen</Text>
            </div>
          </div>

          <div>
            <Text strong>2. Direct Links</Text>
            <div>
              <Text type="secondary">BotFather → /mybots → {bot} → Bot Settings → Direct Links → Create</Text>
            </div>
            {data.direct_links.map((item) => (
              <div key={item.short_name} style={{ marginTop: 4 }}>
                <div>
                  Short name: <CopyValue value={item.short_name} />
                </div>
                <div>
                  Web App URL: <CopyValue value={item.web_app_url} hint={noBaseDomain} />
                </div>
                <div>
                  Ссылка: <CopyValue value={item.link} hint="нужен username бота" />
                </div>
              </div>
            ))}
          </div>

          <div>
            <Text strong>3. Privacy mode</Text>
            <div>
              <Text type="secondary">
                /setprivacy → {bot} → Disable, затем заново добавьте бота в группы — нужно, чтобы бот видел вопросы в
                группах.
              </Text>
            </div>
          </div>

          <div>
            <Text strong>4. Автоматически</Text>
            <div>
              <Text type="secondary">
                Меню команд, описание и кнопка «Портал» настраиваются автоматически при каждом деплое и при
                сохранении токена.
              </Text>
            </div>
          </div>
        </>
      ) : null}
    </Space>
  )
}
