/**
 * Человекочитаемые подписи для технических ключей полей в универсальных
 * админ-формах (AdminRecordEditModal / AdminModulePage), которые строят форму
 * динамически из произвольной строки API. Ключи, которых нет в словаре,
 * проходят через `humanizeFieldKey` — так форма остаётся рабочей для любого
 * источника данных без правки самой формы (достаточно дополнить словарь).
 */
const FIELD_LABELS: Record<string, string> = {
  // Общие поля
  title: 'Название',
  name: 'Название',
  label: 'Метка',
  description: 'Описание',
  note: 'Примечание',
  comment: 'Комментарий',
  amount: 'Сумма',
  sum: 'Сумма',
  sum_uzs: 'Сумма в UZS',
  total_sum: 'Общая сумма',
  debt_sum: 'Сумма долга',
  currency: 'Валюта',
  category: 'Категория',
  status: 'Статус',
  is_active: 'Активно',
  is_enabled: 'Включено',
  is_paid: 'Оплачено',
  is_visible_in_cash_section: 'Видно в разделе «Касса»',
  confirmed: 'Подтверждено',
  closed_manually: 'Закрыто вручную',
  created_at: 'Дата создания',
  created_by: 'Создал (ID)',
  created_by_username: 'Создал',
  created_by_full_name: 'Создал',
  last_edit_at: 'Дата изменения',
  updated_at: 'Дата обновления',
  tenant: 'Компания (tenant)',
  company: 'Компания',
  company_payer: 'Компания-плательщик',
  recipient: 'Получатель',
  recipient_user: 'Получатель',
  recipient_full_name: 'Получатель',
  type: 'Тип',
  kind: 'Вид',
  quantity: 'Количество',

  // Заявки (requests)
  expense_id: 'ID расхода',
  expense_link: 'Ссылка на расход',
  expense_year: 'Год расхода',
  expense_month: 'Месяц расхода',
  expense_day: 'День расхода',
  vendor: 'Поставщик (название)',
  vendor_ref: 'Поставщик',
  vendor_ref_id: 'Поставщик',
  vendor_name: 'Поставщик',
  contract_ref: 'Договор (ID)',
  contract_ref_id: 'Договор',
  contract_ref_info: 'Данные договора',
  contract_label: 'Договор',
  contract_number: 'Номер договора',
  payment_type: 'Тип оплаты',
  urgency: 'Срочность',
  requester: 'Заявитель (ID)',
  requester_username: 'Заявитель',
  payment_purpose: 'Назначение платежа',
  submitted_at: 'Дата подачи',
  payed_at: 'Дата оплаты',
  file_link: 'Файл',
  attachments: 'Вложения',
  billing_date: 'Дата биллинга',
  amortization_months: 'Амортизация (мес.)',
  amortization_start_date: 'Старт амортизации',
  is_amortized: 'Амортизируется',
  amortization_schedule: 'График амортизации',

  // Согласования (approvals)
  step: 'Шаг',
  step_type: 'Тип шага',
  decision: 'Решение',
  decided_at: 'Дата решения',
  approver_user: 'Согласующий (ID)',
  approver_username: 'Согласующий',
  approver_recipient_id: 'ID получателя (Telegram)',
  approver_external_user_id: 'Внешний ID пользователя',
  payment_action_mode: 'Режим оплаты',
  payment_webapp_url: 'URL веб-приложения оплаты',
  gateway_message_id: 'ID сообщения шлюза',
  message_sent: 'Сообщение отправлено',
  message_sent_at: 'Дата отправки сообщения',
  resend_count: 'Кол-во повторных отправок',
  can_resend: 'Можно повторить отправку',
  resend_available_at: 'Повтор доступен с',
  telegram_chat_id: 'Telegram чат ID',

  // Инвестиции
  payout_schedule: 'График выплат',
  payout_date: 'Дата выплаты',
  date: 'Дата',
  payment_amount: 'Оплаченная сумма',
  remaining_amount: 'Остаток',
  return_type: 'Тип выплаты',
  created_return: 'Созданная выплата',
  cbu_usd_uzs_rate: 'Курс ЦБ USD/UZS',
  uses_companies: 'Используются компании',
  allowed_return_types: 'Разрешённые типы выплат',

  // Касса / банк / корп. карта
  external_id: 'Внешний ID',
  expense_at: 'Дата расхода',
  revenue_at: 'Дата дохода',
  payload: 'Доп. данные',
  has_request: 'Есть заявка',
  has_paid_request: 'Есть оплаченная заявка',
  matched_request_id: 'ID связанной заявки',
  request_required: 'Нужна заявка',
  wallet_id: 'Кошелёк',
  bank_expense_exists: 'Есть расход в банке',
  revenue_date: 'Дата дохода',
  source_year: 'Год источника',
  direction: 'Направление',
  organization: 'Организация',
  unit: 'Подразделение',
  employee: 'Сотрудник',
  cash_type: 'Тип кассы',
  account: 'Счёт',
  operation: 'Операция',
  counterparty: 'Контрагент',
  row_no: '№ строки',
  doc_date: 'Дата документа',
  process_date: 'Дата обработки',
  doc_no: '№ документа',
  account_name: 'Наименование счёта',
  inn: 'ИНН',
  account_no: 'Номер счёта',
  mfo: 'МФО',
  kredit_turnover: 'Кредитовый оборот',

  // Кошельки
  code: 'Код',
  sort_order: 'Порядок сортировки',
  is_default_for_currency: 'По умолчанию для валюты',
  wallet_is_visible_in_cash_section: 'Видно в разделе «Касса»',
  account_number: 'Номер счёта',
  external_ref: 'Внешняя ссылка',
  wallet_type: 'Тип кошелька',
  opening_balance: 'Начальный баланс',
  opening_balance_at: 'Дата начального баланса',
  cash_register_id: 'Касса',
  bank_account_id: 'Банковский счёт',
  corporate_card_account_id: 'Корп. карта (счёт)',

  // Зарплата (payroll)
  line_no: '№ строки',
  item: 'Статья',
  days_plan: 'Дней по плану',
  days_fact: 'Дней по факту',
  period_start: 'Начало периода',
  period_end: 'Конец периода',
  approval: 'Согласование',
  doc_id: '№ документа',
  lines_count: 'Кол-во строк',

  // Заметки (notes)
  target_type: 'Тип объекта',
  target_id: 'ID объекта',
  message: 'Сообщение',
  delivery_status: 'Статус доставки',
  delivery_error: 'Ошибка доставки',
  sent_at: 'Дата отправки',

  // Долги клиентов
  snapshot_at: 'Дата среза',
  doc_type: 'Тип документа',
  client: 'Клиент',
  client_id: 'ID клиента',
  cert_discount: 'Скидка (сертификат)',

  // Автозаявки
  day_of_month: 'День месяца',
  title_template: 'Шаблон названия',
  description_template: 'Шаблон описания',
  billing_month_mode: 'Режим месяца биллинга',
  last_run_month: 'Последний месяц запуска',
}

/** Фолбэк для ключей вне словаря: snake_case → «Snake case». */
function humanizeFieldKey(key: string): string {
  const words = key.split('_').filter(Boolean)
  if (!words.length) return key
  const [first, ...rest] = words
  return [first.charAt(0).toUpperCase() + first.slice(1), ...rest].join(' ')
}

/** Подпись поля для универсальных админ-форм: словарь → иначе humanize. */
export function getFieldLabel(key: string): string {
  return FIELD_LABELS[key] ?? humanizeFieldKey(key)
}
