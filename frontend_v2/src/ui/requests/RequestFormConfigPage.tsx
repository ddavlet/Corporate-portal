import { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Divider,
  Input,
  InputNumber,
  Select,
  Skeleton,
  Space,
  Tabs,
  Tag,
  Typography,
  message,
} from 'antd'
import { ArrowLeftOutlined, PlusOutlined, SaveOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import {
  createRequesterUser,
  getRequestFormConfig,
  updateRequestFormConfig,
  type RequestFormConfigPaymentTypeItem,
  type RequestFormConfigPurposeItem,
  type RequestFormConfigResponse,
} from '../../lib/api'
import { labelBlockAboveField } from '../formSpacing'

const PAYMENT_TYPES = ['Наличные', 'Перечисление', 'Пополнение', 'Платежная карта'] as const

function emptyPaymentTypeRow(pt: string): RequestFormConfigPaymentTypeItem {
  return {
    payment_type: pt,
    is_enabled: false,
    requester_ids: [],
    vendor_ids: [],
    payment_purposes: [],
    default_title: '',
    default_company_payer: '',
    default_description: '',
    default_amount: null,
    default_currency: 'UZS',
    default_urgency: 'Обычно',
    default_billing_days_offset: 0,
    default_payment_purpose: '',
    default_vendor_id: null,
  }
}

function normalizeConfig(resp: RequestFormConfigResponse): RequestFormConfigResponse {
  const existing = new Map(resp.payment_types.map((p) => [p.payment_type, p]))
  const normalized: RequestFormConfigPaymentTypeItem[] = PAYMENT_TYPES.map((pt) => {
    const row = existing.get(pt)
    return row ? { ...emptyPaymentTypeRow(pt), ...row, payment_type: pt } : emptyPaymentTypeRow(pt)
  })
  return {
    ...resp,
    payment_types: normalized,
    category_candidates: resp.category_candidates ?? [],
  }
}

export function RequestFormConfigPage() {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<string>(PAYMENT_TYPES[0])
  const [data, setData] = useState<RequestFormConfigResponse | null>(null)
  const [creatingRequester, setCreatingRequester] = useState(false)
  const [newReqUsername, setNewReqUsername] = useState('')
  const [newReqFullName, setNewReqFullName] = useState('')
  const [newReqTgChat, setNewReqTgChat] = useState<number | null>(null)
  const [newReqTgFrom, setNewReqTgFrom] = useState<number | null>(null)
  const [newCategoryName, setNewCategoryName] = useState('')

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setLoading(true)
      setError(null)
      try {
        const normalized = normalizeConfig(await getRequestFormConfig())
        if (!cancelled) setData(normalized)
      } catch (e: any) {
        if (!cancelled) setError(e?.message || 'Ошибка загрузки конфигурации')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const requesterOptions = useMemo(
    () => (data?.requester_candidates || []).map((u) => ({ label: u.username, value: u.id })),
    [data],
  )
  const vendorOptions = useMemo(
    () =>
      (data?.vendor_candidates || []).map((v) => {
        const bits = [v.kind === 'cash' ? 'Наличные' : 'Перечисление', v.name]
        if (v.inn) bits.push(`ИНН ${v.inn}`)
        if (v.account_number) bits.push(v.account_number)
        return { label: bits.join(' · '), value: v.id }
      }),
    [data],
  )
  const categoryOptions = useMemo(() => (data?.category_candidates || []).map((c) => ({ label: c, value: c })), [data])

  const updateCategoryCandidates = (names: string[]) => {
    setData((prev) => (prev ? { ...prev, category_candidates: names } : prev))
  }

  const addCategory = () => {
    if (!data) return
    const name = newCategoryName.trim()
    if (!name) {
      message.warning('Введите название категории')
      return
    }
    const current = data.category_candidates || []
    if (current.includes(name)) {
      message.info('Такая категория уже в списке')
      return
    }
    updateCategoryCandidates([...current, name])
    setNewCategoryName('')
  }

  const removeCategory = (name: string) => {
    if (!data) return
    updateCategoryCandidates((data.category_candidates || []).filter((c) => c !== name))
  }

  const updatePaymentType = (paymentType: string, patch: Partial<RequestFormConfigPaymentTypeItem>) => {
    setData((prev) => {
      if (!prev) return prev
      return {
        ...prev,
        payment_types: prev.payment_types.map((pt) => (pt.payment_type === paymentType ? { ...pt, ...patch } : pt)),
      }
    })
  }

  const addPurpose = (paymentType: string) => {
    setData((prev) => {
      if (!prev) return prev
      return {
        ...prev,
        payment_types: prev.payment_types.map((pt) =>
          pt.payment_type === paymentType
            ? {
                ...pt,
                payment_purposes: [...pt.payment_purposes, { name: '', category: '', is_active: true }],
              }
            : pt,
        ),
      }
    })
  }

  const updatePurpose = (paymentType: string, idx: number, patch: Partial<RequestFormConfigPurposeItem>) => {
    setData((prev) => {
      if (!prev) return prev
      return {
        ...prev,
        payment_types: prev.payment_types.map((pt) =>
          pt.payment_type === paymentType
            ? {
                ...pt,
                payment_purposes: pt.payment_purposes.map((p, i) => (i === idx ? { ...p, ...patch } : p)),
              }
            : pt,
        ),
      }
    })
  }

  const removePurpose = (paymentType: string, idx: number) => {
    setData((prev) => {
      if (!prev) return prev
      return {
        ...prev,
        payment_types: prev.payment_types.map((pt) =>
          pt.payment_type === paymentType
            ? { ...pt, payment_purposes: pt.payment_purposes.filter((_, i) => i !== idx) }
            : pt,
        ),
      }
    })
  }

  const addRequester = async () => {
    if (!data) return
    const u = newReqUsername.trim()
    const fn = newReqFullName.trim()
    if (!u || !fn) {
      message.warning('Укажите логин и полное имя')
      return
    }
    if (/\s/.test(u)) {
      message.warning('Логин не должен содержать пробелы')
      return
    }
    setCreatingRequester(true)
    try {
      const next = await createRequesterUser({
        username: u,
        full_name: fn,
        ...(newReqTgChat != null ? { telegram_chat_id: newReqTgChat } : {}),
        ...(newReqTgFrom != null ? { telegram_from_id: newReqTgFrom } : {}),
      })
      setData(normalizeConfig(next))
      setNewReqUsername('')
      setNewReqFullName('')
      setNewReqTgChat(null)
      setNewReqTgFrom(null)
      message.success('Заявитель добавлен')
    } catch (e: any) {
      message.error(e?.message || 'Не удалось создать заявителя')
    } finally {
      setCreatingRequester(false)
    }
  }

  const save = async () => {
    if (!data) return
    setSaving(true)
    setError(null)
    try {
      const categoriesFromPurposes = new Set<string>()
      for (const pt of data.payment_types) {
        for (const p of pt.payment_purposes) {
          const c = String(p.category || '').trim()
          if (c) categoriesFromPurposes.add(c)
        }
      }
      const manual = (data.category_candidates || []).map((c) => String(c).trim()).filter(Boolean)
      const category_candidates = [...new Set([...manual, ...categoriesFromPurposes])].sort((a, b) =>
        a.localeCompare(b, 'ru'),
      )

      const payload = {
        category_candidates,
        payment_types: data.payment_types.map((pt) => ({
          payment_type: pt.payment_type,
          is_enabled: pt.is_enabled,
          requester_ids: pt.requester_ids,
          vendor_ids: pt.vendor_ids,
          payment_purposes: pt.payment_purposes
            .map((p) => ({
              name: String(p.name || '').trim(),
              category: String(p.category || '').trim(),
              is_active: p.is_active !== false,
            }))
            .filter((p) => p.name),
          default_title: String(pt.default_title ?? ''),
          default_company_payer: String(pt.default_company_payer ?? '').trim(),
          default_description: String(pt.default_description ?? ''),
          default_amount: pt.default_amount === '' || pt.default_amount == null ? null : pt.default_amount,
          default_currency: pt.default_currency ?? 'UZS',
          default_urgency: pt.default_urgency ?? 'Обычно',
          default_billing_days_offset: pt.default_billing_days_offset ?? 0,
          default_payment_purpose: String(pt.default_payment_purpose ?? '').trim(),
          default_vendor_id: pt.default_vendor_id ?? null,
        })),
      }

      setData(normalizeConfig(await updateRequestFormConfig(payload)))
      message.success('Сохранено')
    } catch (e: any) {
      setError(e?.message || 'Ошибка сохранения')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card>
      <Button type="link" icon={<ArrowLeftOutlined />} onClick={() => navigate('/settings')} style={{ padding: 0 }}>
        Назад к настройкам
      </Button>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        Настройка формы заявки
      </Typography.Title>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
        Админ-конфигурация доступных типов оплаты, заявителей, поставщиков и назначений платежа. Компания-плательщик
        задаётся здесь для каждого типа оплаты (блок «Значения по умолчанию» на вкладке типа) и подставляется при
        создании заявки и в автозаявках.
      </Typography.Paragraph>

      <Divider />

      {loading ? <Skeleton active /> : null}
      {error ? <Alert type="error" showIcon message={error} style={{ marginBottom: 12 }} /> : null}

      {!loading && data ? (
        <>
          <Space direction="vertical" size={12} style={{ display: 'flex' }}>
            <Typography.Text strong style={labelBlockAboveField}>
              Новый заявитель
            </Typography.Text>
            <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
              Создаётся пользователь с ролью заявителя: доступ к заявкам и связанным разделам (поставщики, заметки в
              рамках модуля заявок). Без кассы, банка, зарплаты и корпоративной карты.
            </Typography.Paragraph>
            <Space wrap align="start" style={{ width: '100%' }}>
              <div style={{ minWidth: 200, flex: '1 1 200px' }}>
                <Typography.Text type="secondary" style={{ display: 'block', marginBottom: 4 }}>
                  Логин (username)
                </Typography.Text>
                <Input
                  value={newReqUsername}
                  onChange={(e) => setNewReqUsername(e.target.value)}
                  placeholder="login"
                  autoComplete="off"
                />
              </div>
              <div style={{ minWidth: 200, flex: '1 1 200px' }}>
                <Typography.Text type="secondary" style={{ display: 'block', marginBottom: 4 }}>
                  Полное имя
                </Typography.Text>
                <Input
                  value={newReqFullName}
                  onChange={(e) => setNewReqFullName(e.target.value)}
                  placeholder="Иван Иванов"
                />
              </div>
              <div style={{ minWidth: 160, flex: '0 1 160px' }}>
                <Typography.Text type="secondary" style={{ display: 'block', marginBottom: 4 }}>
                  Telegram chat id (необяз.)
                </Typography.Text>
                <InputNumber
                  style={{ width: '100%' }}
                  value={newReqTgChat}
                  onChange={(v) => setNewReqTgChat(typeof v === 'number' ? v : null)}
                  placeholder="—"
                />
              </div>
              <div style={{ minWidth: 160, flex: '0 1 160px' }}>
                <Typography.Text type="secondary" style={{ display: 'block', marginBottom: 4 }}>
                  Telegram from id (необяз.)
                </Typography.Text>
                <InputNumber
                  style={{ width: '100%' }}
                  value={newReqTgFrom}
                  onChange={(v) => setNewReqTgFrom(typeof v === 'number' ? v : null)}
                  placeholder="—"
                />
              </div>
              <Button type="primary" loading={creatingRequester} onClick={addRequester} style={{ alignSelf: 'flex-end' }}>
                Создать заявителя
              </Button>
            </Space>
          </Space>

          <Divider />

          <Space direction="vertical" size={12} style={{ display: 'flex' }}>
            <Typography.Text strong style={labelBlockAboveField}>
              Типы оплаты
            </Typography.Text>
            <Space wrap>
              {data.payment_types.map((pt) => (
                <Checkbox
                  key={pt.payment_type}
                  checked={pt.is_enabled}
                  onChange={(e) => updatePaymentType(pt.payment_type, { is_enabled: e.target.checked })}
                >
                  {pt.payment_type}
                </Checkbox>
              ))}
            </Space>
          </Space>

          <Divider />

          <Space direction="vertical" size={12} style={{ display: 'flex' }}>
            <Typography.Text strong style={labelBlockAboveField}>
              Новые категории (для назначений платежа)
            </Typography.Text>
            <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
              Добавляйте названия по одному — они появятся в списке категорий в строках «Назначение платежа» ниже. Категорию,
              убранную из списка и сохранённую так, больше не показываем в подсказках (в справочнике она становится
              неактивной).
            </Typography.Paragraph>
            <Space wrap align="end" style={{ width: '100%' }}>
              <Input
                style={{ minWidth: 220, maxWidth: 400, flex: '1 1 220px' }}
                placeholder="Название категории"
                value={newCategoryName}
                onChange={(e) => setNewCategoryName(e.target.value)}
                onPressEnter={() => addCategory()}
                autoComplete="off"
              />
              <Button type="primary" onClick={addCategory}>
                Добавить категорию
              </Button>
            </Space>
            {(data.category_candidates || []).length > 0 ? (
              <Space wrap size={[8, 8]}>
                {(data.category_candidates || []).map((c) => (
                  <Tag key={c} closable onClose={() => removeCategory(c)}>
                    {c}
                  </Tag>
                ))}
              </Space>
            ) : (
              <Typography.Text type="secondary">Пока нет добавленных категорий.</Typography.Text>
            )}
          </Space>

          <Divider />

          <Tabs
            activeKey={activeTab}
            onChange={setActiveTab}
            items={data.payment_types.map((pt) => ({
              key: pt.payment_type,
              label: pt.payment_type,
              children: (
                <Space direction="vertical" size={16} style={{ display: 'flex' }}>
                  {!pt.is_enabled ? (
                    <Alert
                      type="warning"
                      showIcon
                      message="Тип оплаты выключен. Пользователи не смогут создать заявку с этим типом."
                    />
                  ) : null}

                  <div>
                    <Typography.Text strong style={labelBlockAboveField}>
                      Заявители (requesters)
                    </Typography.Text>
                    <div>
                      <Select
                        mode="multiple"
                        style={{ width: '100%' }}
                        placeholder="Выберите заявителей"
                        value={pt.requester_ids}
                        onChange={(value) => updatePaymentType(pt.payment_type, { requester_ids: value })}
                        options={requesterOptions}
                        optionFilterProp="label"
                        showSearch
                      />
                      <Typography.Paragraph type="secondary" style={{ marginTop: 6, marginBottom: 0 }}>
                        В форме создания заявки будут только перечисленные здесь заявители. Если никого не выбрать —
                        шаг «Заявитель» будет пустым, пока администратор не добавит пользователей.
                      </Typography.Paragraph>
                    </div>
                  </div>

                  <div>
                    <Typography.Text strong style={labelBlockAboveField}>
                      Поставщики (vendors)
                    </Typography.Text>
                    <div>
                      <Select
                        mode="multiple"
                        style={{ width: '100%' }}
                        placeholder="Выберите поставщиков"
                        value={pt.vendor_ids}
                        onChange={(value) => updatePaymentType(pt.payment_type, { vendor_ids: value })}
                        options={vendorOptions}
                        optionFilterProp="label"
                        showSearch
                      />
                      <Typography.Paragraph type="secondary" style={{ marginTop: 6, marginBottom: 0 }}>
                        Если список пустой — ограничение не применяется (можно вводить любого поставщика).
                      </Typography.Paragraph>
                    </div>
                  </div>

                  <div>
                    <Space
                      align="center"
                      size="middle"
                      style={{ justifyContent: 'space-between', width: '100%', marginBottom: 12 }}
                    >
                      <Typography.Text strong>Назначения платежа (payment purpose)</Typography.Text>
                      <Button icon={<PlusOutlined />} onClick={() => addPurpose(pt.payment_type)}>
                        Добавить
                      </Button>
                    </Space>

                    {pt.payment_purposes.length === 0 ? (
                      <Alert
                        type="info"
                        showIcon
                        style={{ marginTop: 12 }}
                        message="Список пуст. Если вы добавите назначения, категория будет выставляться автоматически по выбранному назначению."
                      />
                    ) : null}

                    <Space direction="vertical" size={8} style={{ display: 'flex', marginTop: 12 }}>
                      {pt.payment_purposes.map((p, idx) => (
                        <Card key={`${pt.payment_type}:${idx}`} size="small">
                          <Space direction="vertical" size={8} style={{ display: 'flex' }}>
                            <Space wrap style={{ width: '100%' }}>
                              <Input
                                placeholder="Назначение платежа"
                                value={p.name}
                                onChange={(e) => updatePurpose(pt.payment_type, idx, { name: e.target.value })}
                                style={{ width: 360, maxWidth: '100%' }}
                              />
                              <Select
                                placeholder="Категория"
                                value={p.category || undefined}
                                onChange={(value) => updatePurpose(pt.payment_type, idx, { category: value })}
                                options={categoryOptions}
                                style={{ width: 280, maxWidth: '100%' }}
                                showSearch
                                optionFilterProp="label"
                              />
                              <Checkbox
                                checked={p.is_active !== false}
                                onChange={(e) => updatePurpose(pt.payment_type, idx, { is_active: e.target.checked })}
                              >
                                Активно
                              </Checkbox>
                              <Button danger onClick={() => removePurpose(pt.payment_type, idx)}>
                                Удалить
                              </Button>
                            </Space>
                            <Typography.Paragraph type="secondary" style={{ margin: 0 }}>
                              При создании заявки категория будет выставлена автоматически по этому назначению.
                            </Typography.Paragraph>
                          </Space>
                        </Card>
                      ))}
                    </Space>
                  </div>

                  <Divider />
                  <div>
                    <Typography.Text strong style={labelBlockAboveField}>
                      Значения по умолчанию при создании заявки
                    </Typography.Text>
                    <Typography.Paragraph type="secondary" style={{ marginTop: 0, marginBottom: 12 }}>
                      Эти поля подставляются на шаге «Детали»; пользователь может их изменить перед отправкой.
                      Компания-плательщик также используется для автозаявок с этим типом оплаты.
                    </Typography.Paragraph>
                    <Space direction="vertical" size={12} style={{ display: 'flex' }}>
                      <div>
                        <Typography.Text type="secondary" style={labelBlockAboveField}>
                          Компания-плательщик
                        </Typography.Text>
                        <Input
                          style={{ display: 'block', maxWidth: 560 }}
                          placeholder="Например, ООО «Рога и копыта»"
                          value={pt.default_company_payer ?? ''}
                          onChange={(e) =>
                            updatePaymentType(pt.payment_type, { default_company_payer: e.target.value })
                          }
                        />
                      </div>
                      <div>
                        <Typography.Text type="secondary" style={labelBlockAboveField}>
                          Название заявки
                        </Typography.Text>
                        <Input
                          style={{ display: 'block', maxWidth: 560 }}
                          placeholder="Заголовок в списке заявок"
                          value={pt.default_title}
                          onChange={(e) => updatePaymentType(pt.payment_type, { default_title: e.target.value })}
                        />
                      </div>
                      <div>
                        <Typography.Text type="secondary" style={labelBlockAboveField}>
                          Описание
                        </Typography.Text>
                        <Input.TextArea
                          style={{ maxWidth: 560 }}
                          rows={2}
                          value={pt.default_description}
                          onChange={(e) => updatePaymentType(pt.payment_type, { default_description: e.target.value })}
                        />
                      </div>
                      <Space wrap size={16}>
                        <div>
                          <Typography.Text type="secondary" style={labelBlockAboveField}>
                            Сумма
                          </Typography.Text>
                          <InputNumber
                            style={{ display: 'block', width: 160 }}
                            min={0}
                            value={
                              pt.default_amount == null || pt.default_amount === ''
                                ? undefined
                                : Number(pt.default_amount)
                            }
                            onChange={(v) =>
                              updatePaymentType(pt.payment_type, {
                                default_amount: v == null ? null : String(v),
                              })
                            }
                          />
                        </div>
                        <div>
                          <Typography.Text type="secondary" style={labelBlockAboveField}>
                            Валюта
                          </Typography.Text>
                          <Select
                            style={{ display: 'block', width: 120 }}
                            value={pt.default_currency}
                            onChange={(v) => updatePaymentType(pt.payment_type, { default_currency: v })}
                            options={['UZS', 'USD', 'EUR', 'RUB'].map((c) => ({ value: c, label: c }))}
                          />
                        </div>
                        <div>
                          <Typography.Text type="secondary" style={labelBlockAboveField}>
                            Срочность
                          </Typography.Text>
                          <Select
                            style={{ display: 'block', width: 180 }}
                            value={pt.default_urgency}
                            onChange={(v) => updatePaymentType(pt.payment_type, { default_urgency: v })}
                            options={[
                              { value: 'Низко', label: 'Низко' },
                              { value: 'Обычно', label: 'Обычно' },
                              { value: 'Срочно', label: 'Срочно' },
                            ]}
                          />
                        </div>
                        <div>
                          <Typography.Text type="secondary" style={labelBlockAboveField}>
                            Месяц биллинга по умолчанию (смещение в месяцах: 0 — текущий, −1 — предыдущий, 1 — следующий)
                          </Typography.Text>
                          <InputNumber
                            style={{ display: 'block', width: 200 }}
                            min={-1}
                            max={1}
                            value={pt.default_billing_days_offset}
                            onChange={(v) =>
                              updatePaymentType(pt.payment_type, {
                                default_billing_days_offset: typeof v === 'number' ? v : 0,
                              })
                            }
                          />
                        </div>
                      </Space>
                      <div>
                        <Typography.Text type="secondary" style={labelBlockAboveField}>
                          Назначение платежа по умолчанию
                        </Typography.Text>
                        <Select
                          style={{ display: 'block', maxWidth: 560 }}
                          allowClear
                          placeholder="Не задано"
                          value={pt.default_payment_purpose || undefined}
                          onChange={(v) =>
                            updatePaymentType(pt.payment_type, { default_payment_purpose: v ?? '' })
                          }
                          options={pt.payment_purposes
                            .filter((p) => p.is_active !== false && String(p.name || '').trim())
                            .map((p) => ({ value: p.name.trim(), label: p.name.trim() }))}
                        />
                      </div>
                      <div>
                        <Typography.Text type="secondary" style={labelBlockAboveField}>
                          Поставщик по умолчанию
                        </Typography.Text>
                        <Select
                          style={{ display: 'block', maxWidth: 560 }}
                          allowClear
                          placeholder="Не задан"
                          value={pt.default_vendor_id ?? undefined}
                          onChange={(v) =>
                            updatePaymentType(pt.payment_type, { default_vendor_id: v ?? null })
                          }
                          options={(data?.vendor_candidates || [])
                            .filter((v) =>
                              pt.payment_type === 'Наличные' ? v.kind === 'cash' : v.kind === 'transfer',
                            )
                            .map((v) => {
                              const bits = [v.name]
                              if (v.inn) bits.push(`ИНН ${v.inn}`)
                              return { value: v.id, label: bits.join(' · ') }
                            })}
                        />
                      </div>
                    </Space>
                  </div>
                </Space>
              ),
            }))}
          />

          <Divider />

          <Space>
            <Button type="primary" icon={<SaveOutlined />} onClick={save} loading={saving}>
              Сохранить
            </Button>
          </Space>
        </>
      ) : null}
    </Card>
  )
}

