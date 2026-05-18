import { Button } from 'antd'
import type { ButtonProps } from 'antd'
import { RobotOutlined } from '@ant-design/icons'
import { openRequestAiChat } from './requestAiChat'

type RequestAiChatButtonProps = {
  block?: boolean
  size?: ButtonProps['size']
}

export function RequestAiChatButton({ block, size }: RequestAiChatButtonProps) {
  return (
    <Button block={block} size={size} icon={<RobotOutlined />} onClick={() => void openRequestAiChat()}>
      Заявка с ИИ (Бета)
    </Button>
  )
}
