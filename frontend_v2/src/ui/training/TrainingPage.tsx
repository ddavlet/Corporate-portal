import { Alert, Anchor, Card, Col, Divider, List, Row, Space, Typography } from 'antd'
import { trainingErrorInfo, trainingFeedbackInfo, trainingSections } from './trainingContent'

export function TrainingPage() {
  const anchorItems = trainingSections.map((section) => ({
    key: section.id,
    href: `#${section.id}`,
    title: section.title,
  }))

  if (!trainingSections.length) {
    return <Alert type="info" message="Материалы обновляются" showIcon />
  }

  return (
    <Space direction="vertical" size={16} style={{ display: 'flex' }}>
      <Card>
        <Typography.Title level={3} style={{ marginTop: 0 }}>
          Обучалка
        </Typography.Title>
        <Typography.Paragraph style={{ marginBottom: 0 }}>
          Короткие и понятные сценарии по текущему интерфейсу: вход в систему, верхняя панель, раздел заявок в web и Telegram.
        </Typography.Paragraph>
      </Card>

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={7}>
          <Card title="Быстрая навигация">
            <Anchor items={anchorItems} />
          </Card>
        </Col>
        <Col xs={24} lg={17}>
          <Space direction="vertical" size={16} style={{ display: 'flex' }}>
            {trainingSections.map((section) => (
              <Card id={section.id} key={section.id} title={section.title}>
                <Typography.Paragraph type="secondary">Экран: {section.routeHint}</Typography.Paragraph>
                <Typography.Text strong>Когда использовать</Typography.Text>
                <Typography.Paragraph>{section.whenToUse}</Typography.Paragraph>
                <Typography.Text strong>Пошагово</Typography.Text>
                <List
                  size="small"
                  dataSource={section.steps}
                  renderItem={(item, index) => <List.Item>{`${index + 1}. ${item}`}</List.Item>}
                  style={{ marginTop: 8, marginBottom: 8 }}
                />
                <Typography.Text strong>Что должно получиться</Typography.Text>
                <Typography.Paragraph>{section.expectedResult}</Typography.Paragraph>
                <Typography.Text strong>Если возникла ошибка</Typography.Text>
                <Typography.Paragraph style={{ marginBottom: 0 }}>{section.errorHelp}</Typography.Paragraph>
              </Card>
            ))}
          </Space>
        </Col>
      </Row>

      <Card title={trainingFeedbackInfo.title}>
        <Typography.Paragraph style={{ marginBottom: 0 }}>{trainingFeedbackInfo.text}</Typography.Paragraph>
      </Card>

      <Card title={trainingErrorInfo.title}>
        <List
          size="small"
          dataSource={trainingErrorInfo.steps}
          renderItem={(item, index) => <List.Item>{`${index + 1}. ${item}`}</List.Item>}
        />
        <Divider style={{ margin: '12px 0' }} />
        <Typography.Paragraph style={{ marginBottom: 0 }}>
          Если ошибка блокирует работу, пометьте обращение как срочное.
        </Typography.Paragraph>
      </Card>
    </Space>
  )
}
