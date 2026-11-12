import type { ReactNode } from 'react'
import { Button, Empty, Skeleton, Space, Typography, theme } from 'antd'
import { CloseCircleOutlined, ReloadOutlined } from '@ant-design/icons'

export type MobileStateWidgetProps =
  | { state: 'loading'; rows?: number }
  | { state: 'empty'; title: string; description?: ReactNode; action?: ReactNode; icon?: ReactNode }
  | { state: 'error'; title?: string; description?: ReactNode; onRetry?: () => void; retrying?: boolean }

/** Loading, empty and error states of mobile lists and screens: skeleton cards, an empty hint, an error with retry. */
export function MobileStateWidget(props: MobileStateWidgetProps) {
  const { token } = theme.useToken()

  if (props.state === 'loading') {
    const rows = props.rows ?? 3
    return (
      <div role="status" aria-label="Загрузка" aria-busy="true" data-testid="mobile-state-loading">
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          {Array.from({ length: rows }, (_, index) => (
            <div
              key={index}
              style={{ padding: 16, borderRadius: token.borderRadiusLG, background: token.colorBgContainer }}
            >
              <Skeleton active title={{ width: '40%' }} paragraph={{ rows: 2, width: ['90%', '60%'] }} />
            </div>
          ))}
        </Space>
      </div>
    )
  }

  if (props.state === 'empty') {
    return (
      <div data-testid="mobile-state-empty" style={{ padding: '32px 16px', textAlign: 'center' }}>
        <Empty
          // The picture is decoration: antd's simple image carries an svg <title> («No data» / «Empty») that screen
          // readers would announce before the hint. `ant-empty-normal` is the class antd gives the simple image itself.
          className={props.icon ? undefined : 'ant-empty-normal'}
          image={<span aria-hidden="true">{props.icon ?? Empty.PRESENTED_IMAGE_SIMPLE}</span>}
          description={
            <Space direction="vertical" size={4}>
              <Typography.Text strong>{props.title}</Typography.Text>
              {props.description ? (
                <Typography.Text style={{ color: token.colorTextSecondary }}>{props.description}</Typography.Text>
              ) : null}
            </Space>
          }
        >
          {props.action ?? null}
        </Empty>
      </div>
    )
  }

  return (
    <div role="alert" data-testid="mobile-state-error" style={{ padding: '32px 16px', textAlign: 'center' }}>
      <Space direction="vertical" size={12} align="center">
        <CloseCircleOutlined aria-hidden style={{ fontSize: 40, color: token.colorError }} />
        <Typography.Text strong>{props.title ?? 'Не удалось загрузить данные'}</Typography.Text>
        <Typography.Text style={{ color: token.colorTextSecondary }}>
          {props.description ?? 'Проверьте соединение и попробуйте ещё раз.'}
        </Typography.Text>
        {props.onRetry ? (
          <Button icon={<ReloadOutlined />} onClick={props.onRetry} loading={props.retrying}>
            Повторить
          </Button>
        ) : null}
      </Space>
    </div>
  )
}
