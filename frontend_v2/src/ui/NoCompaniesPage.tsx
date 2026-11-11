import { useNavigate } from 'react-router-dom'
import { Button, Result } from 'antd'
import { LogoutOutlined } from '@ant-design/icons'
import { useAuth } from './auth'

/** Shared app host: the signed-in user has no active membership in an active company. */
export function NoCompaniesPage() {
  const navigate = useNavigate()
  const { logout } = useAuth()
  return (
    <div className="login-page">
      <Result
        status="info"
        title="Нет доступных компаний"
        subTitle="Ваша учётная запись не состоит ни в одной активной компании. Обратитесь к администратору компании."
        extra={
          <Button
            icon={<LogoutOutlined />}
            onClick={() => {
              logout()
              navigate('/login', { replace: true })
            }}
          >
            Выйти
          </Button>
        }
      />
    </div>
  )
}
