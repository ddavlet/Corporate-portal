import {
  Alert,
  Button,
  Card,
  DatePicker,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Steps,
  Switch,
  Typography,
  Upload,
  message,
} from 'antd'
import { ArrowLeftOutlined, PlusOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { fundingWalletLabel, vendorKindForPaymentType } from '../../lib/requestPaymentTypes'
import { labelBlockAboveField } from '../formSpacing'
import { formatBillingMonth, isAllowedBillingMonth } from '../../lib/billingMonth'
import { CASH_REGISTER_TRANSFER_HINT_PORTAL, useRequestCreateForm } from './useRequestCreateForm'

const CASH_REGISTER_TRANSFER_HINT_TG = 'Перевод между кассами оформляется в разделе «Касса» плиткой «Перевести между кассами».'

const tgPopupContainer = () => document.body

export type RequestCreatePageProps = {
  /** Базовый путь списка заявок без завершающего «/», например `/tg/requests` */
  requestsBasePath?: string
  /** Мобильная вёрстка для Telegram WebApp */
  variant?: 'portal' | 'telegram'
}

export function RequestCreatePage({ requestsBasePath = '/requests', variant = 'portal' }: RequestCreatePageProps) {
  const isTg = variant === 'telegram'
  const navigate = useNavigate()
  const {
    loading,
    optionsError,
    formOptions,
    step,
    stepItems,
    detailStep,
    requiresRequesterSelection,
    paymentType,
    setPaymentType,
    requesterId,
    setRequesterId,
    allowedRequesters,
    vendorRefId,
    setVendorRefId,
    vendorOptions,
    vendorSearchLoading,
    onVendorSearch,
    contractsRequiredForPt,
    contractRefId,
    setContractRefId,
    contractOptions,
    contractLoading,
    description,
    setDescription,
    amount,
    setAmount,
    currency,
    setCurrency,
    currencyOptions,
    lockedCurrency,
    fundingHint,
    urgency,
    setUrgency,
    paymentPurpose,
    setPaymentPurpose,
    purposeOptions,
    transferPurposeHidden,
    transferHintText,
    billingDate,
    setBillingDate,
    amortizationEnabled,
    setAmortizationEnabled,
    amortizationMonths,
    setAmortizationMonths,
    attachmentFileList,
    setAttachmentFileList,
    submitting,
    goNext,
    goBack,
    submit,
    newVendorOpen,
    setNewVendorOpen,
    newVendorName,
    setNewVendorName,
    newVendorInn,
    setNewVendorInn,
    newVendorAccount,
    setNewVendorAccount,
    newVendorSaving,
    saveNewVendor,
    newContractOpen,
    setNewContractOpen,
    newContractSaving,
    saveNewContract,
    ncNumber,
    setNcNumber,
    ncDateFrom,
    setNcDateFrom,
    ncDateTo,
    setNcDateTo,
    ncAmount,
    setNcAmount,
    ncCurrency,
    setNcCurrency,
    ncTerms,
    setNcTerms,
    ncAcc,
    setNcAcc,
    ncFileList,
    setNcFileList,
  } = useRequestCreateForm({
    requestsBasePath,
    transferHintText: isTg ? CASH_REGISTER_TRANSFER_HINT_TG : CASH_REGISTER_TRANSFER_HINT_PORTAL,
  })

  return (
    <div className={isTg ? 'tg-create-page' : undefined}>
      <Card className={isTg ? 'tg-create-card' : undefined} styles={{ body: isTg ? { padding: '16px 16px 24px' } : undefined }}>
        <Space direction="vertical" size={isTg ? 'middle' : 'large'} style={{ display: 'flex' }}>
          <Button
            type="link"
            icon={<ArrowLeftOutlined />}
            onClick={() => navigate(requestsBasePath)}
            style={{ padding: isTg ? '8px 0' : 0, minHeight: isTg ? 44 : undefined, alignSelf: 'flex-start' }}
          >
            К списку заявок
          </Button>
          <Typography.Title level={4} style={{ margin: 0, fontSize: isTg ? 20 : undefined }}>
            Новая заявка
          </Typography.Title>
        {optionsError ? <Alert type="error" showIcon message={optionsError} /> : null}
        {!loading && !optionsError && formOptions.length === 0 ? (
          <Alert
            type="warning"
            showIcon
            message="Форма не настроена"
            description="Администратор должен включить типы оплаты в Настройки → Заявки — форма создания."
          />
        ) : null}

        <Steps
          size="small"
          current={step}
          items={stepItems}
          direction={isTg ? 'vertical' : 'horizontal'}
          className={isTg ? 'tg-steps' : undefined}
        />

        {step === 0 ? (
          <div className={isTg ? 'tg-field-block' : undefined}>
            <Typography.Text strong style={labelBlockAboveField}>
              Тип оплаты
            </Typography.Text>
            <Select
              placeholder="Выберите тип оплаты"
              size={isTg ? 'large' : undefined}
              style={{ width: '100%', maxWidth: isTg ? undefined : 400 }}
              value={paymentType || undefined}
              onChange={(v) => {
                setPaymentType(v)
                setRequesterId(null)
                setVendorRefId(null)
                setContractRefId(null)
                setPaymentPurpose(null)
                setAmortizationEnabled(false)
                setAmortizationMonths(2)
              }}
              options={formOptions.map((p) => ({ value: p.payment_type, label: p.payment_type }))}
              getPopupContainer={isTg ? tgPopupContainer : undefined}
              popupMatchSelectWidth={isTg ? true : undefined}
            />
          </div>
        ) : null}

        {step === 1 && requiresRequesterSelection ? (
          <div className={isTg ? 'tg-field-block' : undefined}>
            <Typography.Text strong style={labelBlockAboveField}>
              Заявитель
            </Typography.Text>
            {allowedRequesters.length === 0 ? (
              <Alert
                type="warning"
                showIcon
                style={{ maxWidth: isTg ? undefined : 560, borderRadius: 12 }}
                message="Для этого типа оплаты не выбраны заявители"
                description="Укажите заявителей для типа оплаты в Настройки → Заявки — форма создания."
              />
            ) : (
              <Select
                placeholder="Выберите заявителя"
                size={isTg ? 'large' : undefined}
                style={{ width: '100%', maxWidth: isTg ? undefined : 400 }}
                value={requesterId ?? undefined}
                onChange={(v) => setRequesterId(v)}
                options={allowedRequesters.map((r) => ({ value: r.id, label: r.username }))}
                showSearch
                optionFilterProp="label"
                getPopupContainer={isTg ? tgPopupContainer : undefined}
                popupMatchSelectWidth={isTg ? true : undefined}
              />
            )}
          </div>
        ) : null}

        {step === detailStep ? (
          <Space direction="vertical" size="middle" style={{ display: 'flex', width: '100%' }}>
            {isTg ? (
              <>
                <div className="tg-field-block">
                  <Typography.Text strong style={labelBlockAboveField}>
                    Сумма
                  </Typography.Text>
                  <InputNumber
                    size="large"
                    style={{ display: 'block', width: '100%' }}
                    min={0}
                    value={amount ?? undefined}
                    onChange={(v) => setAmount(typeof v === 'number' ? v : null)}
                  />
                </div>
                {fundingHint ? (
                  <Typography.Text type="secondary" style={{ display: 'block' }}>
                    Списание: {fundingWalletLabel(fundingHint, currency)}
                  </Typography.Text>
                ) : null}
                <div className="tg-field-block">
                  <Typography.Text strong style={labelBlockAboveField}>
                    Валюта
                  </Typography.Text>
                  <Select
                    size="large"
                    style={{ display: 'block', width: '100%' }}
                    value={currency}
                    onChange={setCurrency}
                    disabled={Boolean(lockedCurrency)}
                    options={currencyOptions}
                    getPopupContainer={tgPopupContainer}
                    popupMatchSelectWidth
                  />
                </div>
                <div className="tg-field-block">
                  <Typography.Text strong style={labelBlockAboveField}>
                    Срочность
                  </Typography.Text>
                  <Select
                    size="large"
                    style={{ display: 'block', width: '100%' }}
                    value={urgency}
                    onChange={setUrgency}
                    options={[
                      { value: 'Низко', label: 'Низко' },
                      { value: 'Обычно', label: 'Обычно' },
                      { value: 'Срочно', label: 'Срочно' },
                    ]}
                    getPopupContainer={tgPopupContainer}
                    popupMatchSelectWidth
                  />
                </div>
                <div className="tg-field-block">
                  <Typography.Text strong style={labelBlockAboveField}>
                    Месяц биллинга
                  </Typography.Text>
                  <DatePicker
                    size="large"
                    picker="month"
                    style={{ display: 'block', width: '100%' }}
                    format="MM.YYYY"
                    value={billingDate}
                    onChange={(v) => setBillingDate(v ? v.startOf('month') : null)}
                    disabledDate={(current) => !current || !isAllowedBillingMonth(current)}
                    getPopupContainer={tgPopupContainer}
                    inputReadOnly
                  />
                </div>
                <div className="tg-field-block">
                  <Space align="center" size="middle">
                    <Typography.Text strong>Амортизировать расход</Typography.Text>
                    <Switch
                      checked={amortizationEnabled}
                      onChange={(checked) => {
                        setAmortizationEnabled(checked)
                        if (!checked) setAmortizationMonths(2)
                      }}
                    />
                  </Space>
                </div>
                {amortizationEnabled ? (
                  <div className="tg-field-block">
                    <Typography.Text strong style={labelBlockAboveField}>
                      Срок амортизации (мес.)
                    </Typography.Text>
                    <Select
                      size="large"
                      style={{ display: 'block', width: '100%' }}
                      value={amortizationMonths}
                      onChange={setAmortizationMonths}
                      options={[2, 3, 4, 5, 6].map((m) => ({ value: m, label: `${m}` }))}
                      getPopupContainer={tgPopupContainer}
                      popupMatchSelectWidth
                    />
                  </div>
                ) : null}
              </>
            ) : (
              <Space wrap size={16}>
                <div>
                  <Typography.Text strong style={labelBlockAboveField}>
                    Сумма
                  </Typography.Text>
                  <InputNumber
                    style={{ display: 'block', width: 160 }}
                    min={0}
                    value={amount ?? undefined}
                    onChange={(v) => setAmount(typeof v === 'number' ? v : null)}
                  />
                </div>
                {fundingHint ? (
                  <Typography.Text type="secondary" style={{ display: 'block' }}>
                    Списание: {fundingWalletLabel(fundingHint, currency)}
                  </Typography.Text>
                ) : null}
                <div>
                  <Typography.Text strong style={labelBlockAboveField}>
                    Валюта
                  </Typography.Text>
                  <Select
                    style={{ display: 'block', width: 120 }}
                    value={currency}
                    onChange={setCurrency}
                    disabled={Boolean(lockedCurrency)}
                    options={currencyOptions}
                  />
                </div>
                <div>
                  <Typography.Text strong style={labelBlockAboveField}>
                    Срочность
                  </Typography.Text>
                  <Select
                    style={{ display: 'block', width: 180 }}
                    value={urgency}
                    onChange={setUrgency}
                    options={[
                      { value: 'Низко', label: 'Низко' },
                      { value: 'Обычно', label: 'Обычно' },
                      { value: 'Срочно', label: 'Срочно' },
                    ]}
                  />
                </div>
                <div>
                  <Typography.Text strong style={labelBlockAboveField}>
                    Месяц биллинга
                  </Typography.Text>
                  <DatePicker
                    picker="month"
                    style={{ display: 'block', maxWidth: 280 }}
                    format={formatBillingMonth}
                    value={billingDate}
                    onChange={(v) => setBillingDate(v ? v.startOf('month') : null)}
                    disabledDate={(current) => !current || !isAllowedBillingMonth(current)}
                    inputReadOnly
                  />
                </div>
                <div>
                  <Typography.Text strong style={labelBlockAboveField}>
                    Амортизировать расход
                  </Typography.Text>
                  <Switch
                    checked={amortizationEnabled}
                    onChange={(checked) => {
                      setAmortizationEnabled(checked)
                      if (!checked) setAmortizationMonths(2)
                    }}
                  />
                </div>
                {amortizationEnabled ? (
                  <div>
                    <Typography.Text strong style={labelBlockAboveField}>
                      Срок амортизации (мес.)
                    </Typography.Text>
                    <Select
                      style={{ display: 'block', width: 180 }}
                      value={amortizationMonths}
                      onChange={setAmortizationMonths}
                      options={[2, 3, 4, 5, 6].map((m) => ({ value: m, label: `${m}` }))}
                    />
                  </div>
                ) : null}
              </Space>
            )}
            {purposeOptions.length > 0 || transferPurposeHidden ? (
              <div className={isTg ? 'tg-field-block' : undefined}>
                {purposeOptions.length > 0 ? (
                  <>
                    <Typography.Text strong style={labelBlockAboveField}>
                      Назначение платежа
                    </Typography.Text>
                    <Select
                      placeholder="Выберите назначение"
                      size={isTg ? 'large' : undefined}
                      style={{ display: 'block', width: '100%', maxWidth: isTg ? undefined : 560 }}
                      value={paymentPurpose || undefined}
                      onChange={setPaymentPurpose}
                      options={purposeOptions}
                      getPopupContainer={isTg ? tgPopupContainer : undefined}
                      popupMatchSelectWidth={isTg ? true : undefined}
                    />
                  </>
                ) : null}
                {transferPurposeHidden ? (
                  <Typography.Text
                    type="secondary"
                    style={{ display: 'block', marginTop: purposeOptions.length > 0 ? 8 : 0 }}
                  >
                    {transferHintText}
                  </Typography.Text>
                ) : null}
              </div>
            ) : null}
            <div className={isTg ? 'tg-field-block' : undefined}>
              <Space align="center" size="middle" wrap style={{ marginBottom: 8 }}>
                <Typography.Text strong>Поставщик</Typography.Text>
                <Button type="link" icon={<PlusOutlined />} onClick={() => setNewVendorOpen(true)} style={{ paddingInline: 0 }}>
                  Новый поставщик
                </Button>
              </Space>
              <Select
                placeholder="Поиск по названию / ИНН"
                size={isTg ? 'large' : undefined}
                style={{ display: 'block', width: '100%', maxWidth: isTg ? undefined : 560 }}
                showSearch
                filterOption={false}
                loading={vendorSearchLoading}
                value={vendorRefId ?? undefined}
                onChange={(v) => {
                  setVendorRefId(v)
                  setContractRefId(null)
                }}
                onSearch={onVendorSearch}
                options={vendorOptions}
                allowClear
                getPopupContainer={isTg ? tgPopupContainer : undefined}
                popupMatchSelectWidth={isTg ? true : undefined}
              />
            </div>
            {contractsRequiredForPt ? (
              <div className={isTg ? 'tg-field-block' : undefined}>
                <Space align="center" size="middle" wrap style={{ marginBottom: 8 }}>
                  <Typography.Text strong>Договор</Typography.Text>
                  <Button
                    type="link"
                    icon={<PlusOutlined />}
                    disabled={!vendorRefId}
                    onClick={() => {
                      if (!vendorRefId) {
                        message.warning('Сначала выберите поставщика')
                        return
                      }
                      setNcNumber('')
                      setNcDateFrom('')
                      setNcDateTo('')
                      setNcAmount(null)
                      setNcCurrency(currency || 'UZS')
                      setNcTerms('')
                      setNcAcc('')
                      setNcFileList([])
                      setNewContractOpen(true)
                    }}
                    style={{ paddingInline: 0 }}
                  >
                    Новый договор
                  </Button>
                </Space>
                <Select
                  placeholder={vendorRefId ? 'Выберите договор' : 'Сначала выберите поставщика'}
                  size={isTg ? 'large' : undefined}
                  style={{ display: 'block', width: '100%', maxWidth: isTg ? undefined : 560 }}
                  loading={contractLoading}
                  value={contractRefId ?? undefined}
                  onChange={(v) => setContractRefId(v)}
                  options={contractOptions}
                  allowClear
                  getPopupContainer={isTg ? tgPopupContainer : undefined}
                  popupMatchSelectWidth={isTg ? true : undefined}
                />
              </div>
            ) : null}
            <div className={isTg ? 'tg-field-block' : undefined}>
              <Typography.Text strong style={labelBlockAboveField}>
                Описание
              </Typography.Text>
              <Input.TextArea
                style={{ maxWidth: isTg ? undefined : 560 }}
                rows={isTg ? 4 : 3}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
            </div>
            <div className={isTg ? 'tg-field-block' : undefined}>
              <Typography.Text strong style={labelBlockAboveField}>
                Вложения
              </Typography.Text>
              <Upload
                multiple
                beforeUpload={() => false}
                fileList={attachmentFileList}
                onChange={({ fileList }) => setAttachmentFileList(fileList)}
              >
                <Button icon={<PlusOutlined />} size={isTg ? 'large' : undefined}>
                  Выбрать файлы
                </Button>
              </Upload>
            </div>
          </Space>
        ) : null}

        {!isTg ? (
          <Space>
            {step > 0 ? <Button onClick={goBack}>Назад</Button> : null}
            {step < detailStep ? (
              <Button type="primary" onClick={goNext} disabled={loading || formOptions.length === 0}>
                Далее
              </Button>
            ) : (
              <Button type="primary" loading={submitting} onClick={() => void submit()}>
                Создать заявку
              </Button>
            )}
          </Space>
        ) : null}
      </Space>

      <Modal
        title="Новый поставщик"
        open={newVendorOpen}
        onCancel={() => setNewVendorOpen(false)}
        onOk={() => void saveNewVendor()}
        confirmLoading={newVendorSaving}
        okText="Сохранить"
        centered
        width={isTg ? 'min(calc(100vw - 24px), 400px)' : undefined}
        styles={
          isTg
            ? {
                body: { maxHeight: 'min(72dvh, 520px)', overflowY: 'auto' },
              }
            : undefined
        }
        getContainer={isTg ? () => document.body : undefined}
      >
        <Typography.Paragraph type="secondary">
          Тип: {vendorKindForPaymentType(paymentType ?? '') === 'cash' ? 'наличные' : 'перечисление'} (по выбранному
          типу оплаты заявки).
        </Typography.Paragraph>
        <Form layout="vertical">
          <Form.Item label="Наименование" required>
            <Input value={newVendorName} onChange={(e) => setNewVendorName(e.target.value)} />
          </Form.Item>
          {paymentType && vendorKindForPaymentType(paymentType) !== 'cash' ? (
            <Form.Item label="ИНН" required>
              <Input value={newVendorInn} onChange={(e) => setNewVendorInn(e.target.value)} />
            </Form.Item>
          ) : null}
          <Form.Item label="Расчётный счёт (необязательно)">
            <Input value={newVendorAccount} onChange={(e) => setNewVendorAccount(e.target.value)} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="Новый договор"
        open={newContractOpen}
        onCancel={() => setNewContractOpen(false)}
        onOk={() => void saveNewContract()}
        confirmLoading={newContractSaving}
        okText="Сохранить"
        centered
        width={isTg ? 'min(calc(100vw - 24px), 440px)' : 520}
        getContainer={isTg ? () => document.body : undefined}
      >
        <Typography.Paragraph type="secondary">
          Поставщик: текущий выбор в заявке (из справочника).
        </Typography.Paragraph>
        <Form layout="vertical">
          <Form.Item label="Номер договора" required>
            <Input value={ncNumber} onChange={(e) => setNcNumber(e.target.value)} />
          </Form.Item>
          <Space wrap>
            <Form.Item label="Дата с" required>
              <Input type="date" value={ncDateFrom} onChange={(e) => setNcDateFrom(e.target.value)} />
            </Form.Item>
            <Form.Item label="Дата по">
              <Input type="date" value={ncDateTo} onChange={(e) => setNcDateTo(e.target.value)} />
            </Form.Item>
          </Space>
          <Space wrap>
            <Form.Item label="Сумма">
              <InputNumber min={0.01} step={0.01} value={ncAmount ?? undefined} onChange={(v) => setNcAmount(typeof v === 'number' ? v : null)} />
            </Form.Item>
            <Form.Item label="Валюта">
              <Select
                style={{ width: 120 }}
                value={ncCurrency}
                onChange={setNcCurrency}
                options={['UZS', 'USD', 'EUR', 'RUB'].map((c) => ({ value: c, label: c }))}
              />
            </Form.Item>
          </Space>
          <Form.Item label="Расчётный счёт">
            <Input value={ncAcc} onChange={(e) => setNcAcc(e.target.value)} />
          </Form.Item>
          <Form.Item label="Условия">
            <Input.TextArea rows={2} value={ncTerms} onChange={(e) => setNcTerms(e.target.value)} />
          </Form.Item>
          <Form.Item label="Файл">
            <Upload maxCount={1} fileList={ncFileList} beforeUpload={() => false} onChange={({ fileList }) => setNcFileList(fileList)}>
              <Button>Выбрать файл</Button>
            </Upload>
          </Form.Item>
        </Form>
      </Modal>
    </Card>

      {isTg ? (
        <div className="tg-sticky-actions">
          {step > 0 ? (
            <Button size="large" onClick={goBack}>
              Назад
            </Button>
          ) : (
            <span style={{ width: 88, flexShrink: 0 }} aria-hidden />
          )}
          {step < detailStep ? (
            <Button type="primary" size="large" onClick={goNext} disabled={loading || formOptions.length === 0}>
              Далее
            </Button>
          ) : (
            <Button type="primary" size="large" loading={submitting} onClick={() => void submit()}>
              Создать заявку
            </Button>
          )}
        </div>
      ) : null}
    </div>
  )
}
