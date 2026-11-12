import type { ReactNode } from 'react'
import { theme } from 'antd'
import { mobileToneTextColor } from './mobileActionsTheme'

type FieldProps = {
  label: string
  /** The control's id: the label is a real <label>. */
  htmlFor?: string
  /** Id of the label text, for groups that point at it with aria-labelledby. */
  labelId?: string
  error?: string
  errorId?: string
  children: ReactNode
}

/** A field of the wizard: the label above, the control, its error in red under it. */
export function Field({ label, htmlFor, labelId, error, errorId, children }: FieldProps) {
  const { token } = theme.useToken()
  const labelStyle = { display: 'block', marginBottom: 6, fontWeight: 600, color: token.colorText }
  return (
    <div style={{ minWidth: 0 }}>
      {htmlFor ? (
        <label htmlFor={htmlFor} id={labelId} style={labelStyle}>
          {label}
        </label>
      ) : (
        <span id={labelId} style={labelStyle}>
          {label}
        </span>
      )}
      {children}
      <FieldError id={errorId} error={error} />
    </div>
  )
}

export function FieldError({ id, error }: { id?: string; error?: string }) {
  const { token } = theme.useToken()
  if (!error) return null
  return (
    <div id={id} role="alert" style={{ marginTop: 4, color: mobileToneTextColor('error', token), fontSize: 14 }}>
      {error}
    </div>
  )
}
