import { Fragment, useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import {
  Alert,
  Button,
  Card,
  DatePicker,
  Divider,
  InputNumber,
  Modal,
  Result,
  Select,
  Skeleton,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
  message,
} from 'antd'
import { ArrowLeftOutlined, SendOutlined, UserOutlined } from '@ant-design/icons'
import { Link, useNavigate } from 'react-router-dom'
import dayjs, { type Dayjs } from 'dayjs'

import {
  InvestReportUnavailableError,
  getInvestReportConfig,
  listInvestReportDispatches,
  previewInvestReport,
  saveInvestReportConfig,
  sendInvestReportNow,
  sendInvestReportTest,
  type InvestReportConfigDto,
  type InvestReportConfigResponse,
  type InvestReportDispatchDto,
  type InvestReportParams,
} from '../../lib/api'

const PREVIEW_DEBOUNCE_MS = 500

const WEEKDAYS = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье']
const MONTHS = [
  'Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
  'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь',
]
const KIND_LABELS: Record<InvestReportDispatchDto['kind'], string> = {
  scheduled: 'По расписанию',
  manual: 'Вручную в группу',
  test: 'Пробный в личку',
}

function unescapeHtml(text: string): string {
  return text.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&')
}

/** Telegram HTML of the report → React nodes. Only <b> is honoured; any other markup stays plain text. */
export function renderReportHtml(html: string): ReactNode[] {
  const nodes: ReactNode[] = []
  let bold = false
  html.split(/(<b>|<\/b>)/).forEach((part, i) => {
    if (part === '<b>') bold = true
    else if (part === '</b>') bold = false
    else if (part) nodes.push(bold ? <b key={i}>{unescapeHtml(part)}</b> : <Fragment key={i}>{unescapeHtml(part)}</Fragment>)
  })
  return nodes
}

function toDto(res: InvestReportConfigResponse): InvestReportConfigDto {
  return {
    is_active: res.is_active,
    telegram_chat_id: res.telegram_chat_id,
    weekday: res.weekday,
    send_hour: res.send_hour,
    target_annual_rate: res.target_annual_rate,
    start_month: res.start_month,
    last_payouts_count: res.last_payouts_count,
    late_payment_day: res.late_payment_day,
  }
}

function calcParams(data: InvestReportConfigDto, date: Dayjs | null): InvestReportParams {
  return {
    date: date ? date.format('YYYY-MM-DD') : undefined,
    target_annual_rate: data.target_annual_rate,
    start_month: data.start_month,
    last_payouts_count: data.last_payouts_count,
    late_payment_day: data.late_payment_day,
  }
}

export function InvestmentReportConfigPage() {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [sending, setSending] = useState<'test' | 'group' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [unavailable, setUnavailable] = useState(false)
  const [data, setData] = useState<InvestReportConfigDto | null>(null)
  const [saved, setSaved] = useState<InvestReportConfigDto | null>(null)
  const [chats, setChats] = useState<InvestReportConfigResponse['options']['chats']>([])
  const [previewDate, setPreviewDate] = useState<Dayjs | null>(() => dayjs())
  const [previewText, setPreviewText] = useState<string | null>(null)
  const [previewError, setPreviewError] = useState<string | null>(null)
  const [dispatches, setDispatches] = useState<InvestReportDispatchDto[]>([])

  const applyResponse = (res: InvestReportConfigResponse) => {
    const cfg = toDto(res)
    setData(cfg)
    setSaved(cfg)
    setChats(res.options.chats)
  }

  const reloadDispatches = useCallback(async () => {
    try {
      setDispatches(await listInvestReportDispatches(20))
    } catch {
      setDispatches([])
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const res = await getInvestReportConfig()
        if (cancelled) return
        applyResponse(res)
        void reloadDispatches()
      } catch (e: unknown) {
        if (cancelled) return
        if (e instanceof InvestReportUnavailableError) setUnavailable(true)
        else setError(e instanceof Error ? e.message : 'Ошибка загрузки')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [reloadDispatches])

  // Preview follows the unsaved calculation settings and the date, debounced.
  const previewKey = useMemo(() => (data ? JSON.stringify(calcParams(data, previewDate)) : null), [data, previewDate])
  useEffect(() => {
    if (!previewKey) return
    const params = JSON.parse(previewKey) as InvestReportParams
    const controller = new AbortController()
    const timer = window.setTimeout(async () => {
      try {
        const res = await previewInvestReport(params, controller.signal)
        setPreviewText(res.text)
        setPreviewError(null)
      } catch (e: unknown) {
        if (controller.signal.aborted) return
        setPreviewText(null)
        setPreviewError(e instanceof Error ? e.message : 'Не удалось построить отчёт')
      }
    }, PREVIEW_DEBOUNCE_MS)
    return () => {
      window.clearTimeout(timer)
      controller.abort()
    }
  }, [previewKey])

  const patch = (next: Partial<InvestReportConfigDto>) => setData((prev) => (prev ? { ...prev, ...next } : prev))

  const save = async () => {
    if (!data) return
    if (data.is_active && !data.telegram_chat_id) {
      message.warning('Выберите Telegram-группу, чтобы включить отчёт')
      return
    }
    setSaving(true)
    setError(null)
    try {
      applyResponse(await saveInvestReportConfig(data))
      message.success('Сохранено')
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Ошибка сохранения')
    } finally {
      setSaving(false)
    }
  }

  const reportResult = (res: InvestReportDispatchDto, okText: string) => {
    if (res.status === 'sent') message.success(okText)
    else message.error(res.error || 'Отчёт не доставлен')
  }

  const sendTest = async () => {
    if (!data) return
    setSending('test')
    try {
      reportResult(await sendInvestReportTest(calcParams(data, previewDate)), 'Отчёт отправлен вам в Telegram')
      await reloadDispatches()
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : 'Ошибка отправки')
    } finally {
      setSending(null)
    }
  }

  const savedChat = chats.find((c) => c.id === saved?.telegram_chat_id) ?? null

  const confirmSendNow = () => {
    if (!savedChat) return
    Modal.confirm({
      title: 'Отправить отчёт в группу сейчас?',
      content: `Сегодняшний отчёт уйдёт в группу «${savedChat.name}» с сохранёнными настройками.`,
      okText: 'Отправить',
      cancelText: 'Отмена',
      onOk: async () => {
        setSending('group')
        try {
          reportResult(await sendInvestReportNow(), `Отчёт отправлен в «${savedChat.name}»`)
          await reloadDispatches()
        } catch (e: unknown) {
          message.error(e instanceof Error ? e.message : 'Ошибка отправки')
        } finally {
          setSending(null)
        }
      },
    })
  }

  const back = (
    <Button type="link" icon={<ArrowLeftOutlined />} onClick={() => navigate('/settings')} style={{ padding: 0 }}>
      Назад к настройкам
    </Button>
  )

  if (unavailable) {
    return (
      <Card>
        {back}
        <Result
          status="warning"
          title="Настройка недоступна"
          subTitle="Модуль «Инвестиции» выключен для компании или у вас нет прав: отчёт настраивает администратор или директор."
        />
      </Card>
    )
  }

  const unsaved = data && saved && JSON.stringify(data) !== JSON.stringify(saved)

  return (
    <Card>
      {back}
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        Инвестиции — отчёт для инвесторов
      </Typography.Title>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
        Раз в неделю бот компании отправляет в Telegram-группу отчёт: вложено и выплачено (USD по курсу ЦБ), доходность
        за период, сравнение с целью и последние выплаты.
      </Typography.Paragraph>
      <Divider />
      {loading ? <Skeleton active /> : null}
      {error ? <Alert type="error" showIcon message={error} style={{ marginBottom: 12 }} /> : null}

      {!loading && data ? (
        <Space direction="vertical" size={20} style={{ display: 'flex' }}>
          <Space align="center">
            <Switch checked={data.is_active} onChange={(v) => patch({ is_active: v })} aria-label="Включено" />
            <Typography.Text>Включено</Typography.Text>
          </Space>

          <div>
            <Typography.Title level={5}>Группа</Typography.Title>
            <Space direction="vertical" style={{ display: 'flex' }}>
              <Select
                style={{ width: '100%', maxWidth: 420 }}
                placeholder="Выберите Telegram-группу"
                allowClear
                value={data.telegram_chat_id ?? undefined}
                onChange={(v) => patch({ telegram_chat_id: v ?? null })}
                options={chats.map((c) => ({ value: c.id, label: c.name }))}
                aria-label="Telegram-группа"
              />
              <Typography.Text type="secondary">
                Группы добавляются в <Link to="/settings/telegram-chats">Telegram-группах</Link>. Бот компании должен быть
                участником группы.
              </Typography.Text>
            </Space>
          </div>

          <div>
            <Typography.Title level={5}>Когда</Typography.Title>
            <Space wrap>
              <Select
                style={{ width: 180 }}
                value={data.weekday}
                onChange={(v) => patch({ weekday: v })}
                options={WEEKDAYS.map((label, value) => ({ value, label }))}
                aria-label="День недели"
              />
              <Select
                style={{ width: 120 }}
                value={data.send_hour}
                onChange={(v) => patch({ send_hour: v })}
                options={Array.from({ length: 24 }, (_, h) => ({ value: h, label: `${String(h).padStart(2, '0')}:00` }))}
                aria-label="Час отправки"
              />
              <Typography.Text type="secondary">по Ташкенту</Typography.Text>
            </Space>
          </div>

          <div>
            <Typography.Title level={5}>Расчёт</Typography.Title>
            <Space wrap size={[24, 12]} align="start">
              <Space direction="vertical" size={4}>
                <Typography.Text>Целевая доходность, % годовых</Typography.Text>
                <InputNumber
                  min={0}
                  max={1000}
                  step={0.01}
                  precision={2}
                  decimalSeparator=","
                  placeholder="Без цели"
                  value={data.target_annual_rate === null ? null : Number(data.target_annual_rate)}
                  onChange={(v) => patch({ target_annual_rate: v === null || v === undefined ? null : String(v) })}
                  aria-label="Целевая доходность"
                />
              </Space>
              <Space direction="vertical" size={4}>
                <Typography.Text>Начало расчёта</Typography.Text>
                <Select
                  style={{ width: 260 }}
                  allowClear
                  placeholder="После первой инвестиции года"
                  value={data.start_month ?? undefined}
                  onChange={(v) => patch({ start_month: v ?? null })}
                  options={MONTHS.map((label, i) => ({ value: i + 1, label }))}
                  aria-label="Месяц начала расчёта"
                />
              </Space>
              <Space direction="vertical" size={4}>
                <Typography.Text>Последних выплат в отчёте</Typography.Text>
                <InputNumber
                  min={0}
                  max={10}
                  precision={0}
                  value={data.last_payouts_count}
                  onChange={(v) => patch({ last_payouts_count: v ?? 0 })}
                  aria-label="Число последних выплат"
                />
              </Space>
              <Space direction="vertical" size={4}>
                <Typography.Text>Прошлый месяц ждём до числа</Typography.Text>
                <InputNumber
                  min={1}
                  max={31}
                  precision={0}
                  value={data.late_payment_day}
                  onChange={(v) => patch({ late_payment_day: v ?? 25 })}
                  aria-label="День просрочки"
                />
              </Space>
            </Space>
          </div>

          <Space wrap>
            <Button type="primary" loading={saving} onClick={() => void save()}>
              Сохранить
            </Button>
            {unsaved ? <Typography.Text type="warning">Есть несохранённые изменения</Typography.Text> : null}
          </Space>

          <div>
            <Typography.Title level={5}>Предпросмотр</Typography.Title>
            <Space direction="vertical" style={{ display: 'flex' }}>
              <Space wrap>
                <DatePicker
                  value={previewDate}
                  onChange={(v) => setPreviewDate(v)}
                  format="DD.MM.YYYY"
                  allowClear={false}
                  disabledDate={(d) => d.isAfter(dayjs(), 'day')}
                  aria-label="Дата отчёта"
                />
                <Button icon={<UserOutlined />} loading={sending === 'test'} onClick={() => void sendTest()}>
                  Отправить мне
                </Button>
                <Button
                  icon={<SendOutlined />}
                  loading={sending === 'group'}
                  disabled={!savedChat}
                  onClick={confirmSendNow}
                >
                  Отправить в группу сейчас
                </Button>
              </Space>
              {previewError ? <Alert type="error" showIcon message={previewError} /> : null}
              <div
                data-testid="invest-report-preview"
                style={{
                  whiteSpace: 'pre-wrap',
                  maxWidth: 560,
                  padding: 12,
                  borderRadius: 8,
                  border: '1px solid rgba(5, 5, 5, 0.12)',
                  fontSize: 14,
                }}
              >
                {previewText === null ? <Typography.Text type="secondary">Строим отчёт…</Typography.Text> : renderReportHtml(previewText)}
              </div>
            </Space>
          </div>

          <div>
            <Typography.Title level={5}>Последние отправки</Typography.Title>
            <Table<InvestReportDispatchDto>
              size="small"
              rowKey="id"
              pagination={false}
              dataSource={dispatches}
              locale={{ emptyText: 'Отправок ещё не было' }}
              columns={[
                {
                  title: 'Дата',
                  key: 'date',
                  render: (_, row) =>
                    row.created_at ? dayjs(row.created_at).format('DD.MM.YYYY HH:mm') : dayjs(row.report_date).format('DD.MM.YYYY'),
                },
                { title: 'Тип', dataIndex: 'kind', render: (kind: InvestReportDispatchDto['kind']) => KIND_LABELS[kind] ?? kind },
                {
                  title: 'Статус',
                  dataIndex: 'status',
                  render: (s: InvestReportDispatchDto['status']) =>
                    s === 'sent' ? <Tag color="success">Отправлен</Tag> : <Tag color="error">Ошибка</Tag>,
                },
                { title: 'Группа', key: 'chat', render: (_, row) => row.chat_name || row.chat_id || '—' },
                { title: 'Ошибка', dataIndex: 'error', render: (v: string) => v || '—' },
              ]}
            />
          </div>
        </Space>
      ) : null}
    </Card>
  )
}
