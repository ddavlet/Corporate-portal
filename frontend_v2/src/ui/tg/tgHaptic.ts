const hf = () => window.Telegram?.WebApp?.HapticFeedback

export const tgHaptic = {
  /** Лёгкий отклик для навигационных нажатий (тайлы, строки списка, табы) */
  tap: () => hf()?.selectionChanged(),
  /** Тактильный удар для action-кнопок */
  impact: (style: TelegramHapticImpact = 'light') => hf()?.impactOccurred(style),
}
