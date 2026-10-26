import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { CbuRateAlert } from './CbuRateAlert'

const WARNING = /Курс ЦБ может быть неактуален: нет связи с источником/

describe('CbuRateAlert', () => {
  it('ничего не показывает, если курс на дату есть у всех строк', () => {
    render(<CbuRateAlert rows={[{ date: '2026-10-20', rate_date: '2026-10-20' }]} todayIso="2026-10-26" />)
    expect(screen.queryByText(WARNING)).toBeNull()
  })

  it('показывает дату последнего загруженного курса', () => {
    render(
      <CbuRateAlert
        rows={[
          { date: '2026-10-24', rate_date: '2026-10-22' },
          { date: '2026-10-25', rate_date: '2026-10-22' },
        ]}
        todayIso="2026-10-26"
      />,
    )
    expect(screen.getByText(WARNING).textContent).toContain('(на 22.10.2026)')
  })
})
