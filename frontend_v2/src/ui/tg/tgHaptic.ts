const hf = () => window.Telegram?.WebApp?.HapticFeedback

export const tgHaptic = {
  /** Отклик для навигационных нажатий (тайлы, строки списка, табы) */
  tap: () => hf()?.impactOccurred('light'),
  /** Тактильный удар для action-кнопок */
  impact: (style: TelegramHapticImpact = 'medium') => hf()?.impactOccurred(style),
}
