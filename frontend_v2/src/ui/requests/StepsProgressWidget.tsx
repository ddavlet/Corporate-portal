import { theme } from 'antd'

/**
 * The progress of a phone wizard («Новая заявка», «Собрать из заявок»): one bar per step with its title; the current
 * step is marked for screen readers (`aria-current="step"`).
 */
export function StepsProgressWidget({ titles, current }: { titles: readonly string[]; current: number }) {
  const { token } = theme.useToken()
  return (
    <nav
      aria-label="Шаги"
      style={{ padding: '10px 16px 12px', background: token.colorBgContainer, borderBottom: `1px solid ${token.colorBorderSecondary}` }}
    >
      <ol style={{ display: 'flex', gap: 6, listStyle: 'none', margin: 0, padding: 0 }}>
        {titles.map((title, index) => (
          <li key={title} aria-current={index === current ? 'step' : undefined} style={{ flex: 1, minWidth: 0 }}>
            <div
              aria-hidden
              style={{
                height: 4,
                borderRadius: 2,
                background: index <= current ? token.colorPrimary : token.colorFillSecondary,
              }}
            />
            <div
              className="m-ellipsis"
              style={{
                marginTop: 6,
                fontSize: 13,
                fontWeight: index === current ? 600 : 400,
                color: index === current ? token.colorText : token.colorTextSecondary,
              }}
            >
              {title}
            </div>
          </li>
        ))}
      </ol>
    </nav>
  )
}
