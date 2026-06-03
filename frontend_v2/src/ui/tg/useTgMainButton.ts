import { useEffect, useRef } from 'react'

/** Привязывает tg.MainButton к основному действию страницы. Скрывает кнопку при размонтировании. */
export function useTgMainButton({
  text,
  onClick,
  loading = false,
  disabled = false,
}: {
  text: string
  onClick: () => void
  loading?: boolean
  disabled?: boolean
}) {
  const onClickRef = useRef(onClick)
  onClickRef.current = onClick

  useEffect(() => {
    const btn = window.Telegram?.WebApp?.MainButton
    if (!btn) return

    const handler = () => {
      window.Telegram?.WebApp?.HapticFeedback?.impactOccurred('medium')
      onClickRef.current()
    }
    btn.onClick(handler)
    btn.show()

    return () => {
      btn.offClick(handler)
      btn.hide()
      btn.hideProgress()
    }
  }, [])

  useEffect(() => {
    const btn = window.Telegram?.WebApp?.MainButton
    if (!btn) return
    btn.setText(text)
  }, [text])

  useEffect(() => {
    const btn = window.Telegram?.WebApp?.MainButton
    if (!btn) return
    if (loading) {
      btn.showProgress()
      btn.disable()
    } else if (disabled) {
      btn.hideProgress()
      btn.disable()
    } else {
      btn.hideProgress()
      btn.enable()
    }
  }, [loading, disabled])
}
