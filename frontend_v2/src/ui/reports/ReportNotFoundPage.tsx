import { ArrowLeftOutlined } from '@ant-design/icons'
import { Result } from 'antd'
import { Link } from 'react-router-dom'

/** «← Все отчёты»: back to the cards. */
export function AllReportsLink() {
  return (
    <Link to="/reports">
      <ArrowLeftOutlined /> Все отчёты
    </Link>
  )
}

/** A reports address that names no card: an unknown template or report, or a path of another shape. */
export function ReportNotFoundPage() {
  return <Result status="404" title="Отчёт не найден" extra={<AllReportsLink />} />
}
