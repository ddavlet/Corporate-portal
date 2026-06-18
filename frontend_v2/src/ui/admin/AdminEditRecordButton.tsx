import { useState } from 'react'
import type { CSSProperties } from 'react'
import { Button } from 'antd'
import { EditOutlined } from '@ant-design/icons'
import type { ButtonProps } from 'antd'
import { useTenantAdmin } from '../../lib/useTenantAdmin'
import { AdminRecordEditModal } from './AdminRecordEditModal'

type AnyRecord = Record<string, unknown> & { id?: number | string }

type Props = {
  /** Эндпоинт коллекции, напр. `/api/requests/`. */
  endpoint: string
  record: AnyRecord
  /** Перезагрузка списка после сохранения. */
  onSaved: () => void
  size?: ButtonProps['size']
  block?: boolean
  style?: CSSProperties
  /** Заголовок модалки (по умолчанию «Редактировать запись»). */
  modalTitle?: string
}

/**
 * Кнопка «Редактировать» для админа компании прямо в списке.
 * Для не-админов не рендерится вовсе (graceful degradation) — реальная
 * проверка прав остаётся на бэкенде.
 */
export function AdminEditRecordButton({ endpoint, record, onSaved, size = 'small', block, style, modalTitle }: Props) {
  const { isAdmin } = useTenantAdmin()
  const [open, setOpen] = useState(false)

  if (!isAdmin) return null

  return (
    <>
      <Button
        size={size}
        block={block}
        style={style}
        icon={<EditOutlined />}
        onClick={(e) => {
          e.stopPropagation()
          setOpen(true)
        }}
      >
        Редактировать
      </Button>
      <AdminRecordEditModal
        endpoint={endpoint}
        record={record}
        open={open}
        onClose={() => setOpen(false)}
        onSaved={onSaved}
        title={modalTitle}
      />
    </>
  )
}
