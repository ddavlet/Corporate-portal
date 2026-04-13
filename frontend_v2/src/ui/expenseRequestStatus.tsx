import { Tag, Tooltip } from 'antd'

export type ExpenseRequestStatusInput = {
  request_required?: boolean
  has_paid_request?: boolean
}

export function shouldHighlightMissingRequiredRequest(input: ExpenseRequestStatusInput): boolean {
  return input.request_required === true && input.has_paid_request === false
}

export function renderExpenseRequestStatusTag(input: ExpenseRequestStatusInput) {
  if (input.request_required !== true) {
    return <Tag>Заявка не обязательна</Tag>
  }
  if (input.has_paid_request === false) {
    return (
      <Tooltip title="По этому расходу заявка обязательна, но оплаченная заявка не найдена.">
        <Tag color="gold">Без заявки (обязательна)</Tag>
      </Tooltip>
    )
  }
  return <Tag color="success">Заявка оплачена</Tag>
}
