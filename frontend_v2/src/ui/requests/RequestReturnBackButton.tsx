import { ArrowLeftOutlined } from '@ant-design/icons'
import { Button } from 'antd'
import { useLocation, useNavigate } from 'react-router-dom'
import { readRequestReturnTo } from '../../lib/requestNavigation'

type RequestReturnBackButtonProps = {
  /** Путь «назад», если в state нет returnTo (например, список кассы). */
  fallbackPath: string
  fallbackLabel: string
}

export function RequestReturnBackButton({ fallbackPath, fallbackLabel }: RequestReturnBackButtonProps) {
  const navigate = useNavigate()
  const location = useLocation()
  const returnTo = readRequestReturnTo(location.state)

  const pathname = returnTo?.pathname ?? fallbackPath
  const label = returnTo?.label ?? fallbackLabel

  return (
    <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(pathname)}>
      {label}
    </Button>
  )
}
