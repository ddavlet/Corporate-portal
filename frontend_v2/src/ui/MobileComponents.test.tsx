import { createRef } from 'react'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MobileSheet } from './MobileSheet'
import { MobilePickerSheet } from './MobilePickerSheet'
import { MobileStateWidget } from './MobileStateWidget'
import { MobileCardFeedWidget, type CardFeedSource } from './MobileCardFeedWidget'
import { DesktopOnlyPage } from './DesktopOnlyPage'

const moduleAccess = vi.hoisted(() => ({ loading: false, denied: new Set<string>() }))

vi.mock('./moduleAccess', () => ({
  useModuleAccess: () => ({ loading: moduleAccess.loading, hasAccess: (key: string) => !moduleAccess.denied.has(key) }),
}))

describe('MobileSheet', () => {
  it('shows its content while open and closes from the close button', async () => {
    const onClose = vi.fn()
    const { rerender } = render(
      <MobileSheet open onClose={onClose} title="Фильтры">
        <p>Содержимое листа</p>
      </MobileSheet>,
    )
    expect(await screen.findByText('Содержимое листа')).toBeInTheDocument()
    expect(screen.getByText('Фильтры')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Закрыть' }))
    expect(onClose).toHaveBeenCalledTimes(1)

    rerender(
      <MobileSheet open={false} onClose={onClose} title="Фильтры">
        <p>Содержимое листа</p>
      </MobileSheet>,
    )
    await waitFor(() => expect(screen.queryByText('Содержимое листа')).toBeNull())
  })
})

type Vendor = { id: number; name: string }
const VENDORS: Vendor[] = [
  { id: 1, name: 'Альфа Трейд' },
  { id: 2, name: 'Бета Строй' },
]

describe('MobilePickerSheet', () => {
  function renderPicker(overrides: Partial<Parameters<typeof MobilePickerSheet<Vendor>>[0]> = {}) {
    const load = vi.fn(async (search: string) => VENDORS.filter((v) => v.name.toLowerCase().includes(search.toLowerCase())))
    const onSelect = vi.fn()
    const onCreate = vi.fn()
    const onClose = vi.fn()
    render(
      <MobilePickerSheet<Vendor>
        open
        title="Поставщик"
        onClose={onClose}
        load={load}
        getKey={(v) => v.id}
        renderItem={(v) => v.name}
        onSelect={onSelect}
        createLabel="Новый поставщик"
        onCreate={onCreate}
        {...overrides}
      />,
    )
    return { load, onSelect, onCreate, onClose }
  }

  it('loads the first rows at once and searches after a pause', async () => {
    const { load } = renderPicker()
    expect(await screen.findByRole('button', { name: 'Бета Строй' })).toBeInTheDocument()
    expect(load).toHaveBeenCalledWith('')

    fireEvent.change(screen.getByRole('textbox', { name: 'Поиск' }), { target: { value: 'бета' } })
    await waitFor(() => expect(load).toHaveBeenLastCalledWith('бета'), { timeout: 1500 })
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Альфа Трейд' })).toBeNull())
    expect(screen.getByRole('button', { name: 'Бета Строй' })).toBeInTheDocument()
  })

  it('returns the picked row', async () => {
    const { onSelect } = renderPicker()
    fireEvent.click(await screen.findByRole('button', { name: 'Альфа Трейд' }))
    expect(onSelect).toHaveBeenCalledWith(VENDORS[0])
  })

  it('offers «Новый …» with the typed text', async () => {
    const { onCreate } = renderPicker()
    await screen.findByRole('button', { name: 'Альфа Трейд' })
    fireEvent.change(screen.getByRole('textbox', { name: 'Поиск' }), { target: { value: 'Гамма' } })
    fireEvent.click(screen.getByRole('button', { name: 'Новый поставщик' }))
    expect(onCreate).toHaveBeenCalledWith('Гамма')
  })

  it('shows «Ничего не найдено» and a retry after a failed load', async () => {
    const load = vi.fn().mockRejectedValueOnce(new Error('boom')).mockResolvedValue([])
    renderPicker({ load })
    fireEvent.click(await screen.findByRole('button', { name: /Повторить/ }))
    expect(await screen.findByText('Ничего не найдено')).toBeInTheDocument()
  })

  it('goes back with «Назад»', async () => {
    const { onClose } = renderPicker()
    fireEvent.click(await screen.findByRole('button', { name: 'Назад' }))
    expect(onClose).toHaveBeenCalled()
  })
})

describe('MobileStateWidget', () => {
  it('shows skeletons while loading', () => {
    render(<MobileStateWidget state="loading" />)
    expect(screen.getByRole('status', { name: 'Загрузка' })).toBeInTheDocument()
  })

  it('shows the empty hint with its action', () => {
    render(
      <MobileStateWidget
        state="empty"
        title="Заявок нет"
        description="Попробуйте другие фильтры"
        action={<button type="button">Сбросить фильтры</button>}
      />,
    )
    expect(screen.getByText('Заявок нет')).toBeInTheDocument()
    expect(screen.getByText('Попробуйте другие фильтры')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Сбросить фильтры' })).toBeInTheDocument()
  })

  it('hides the empty picture from screen readers', () => {
    render(<MobileStateWidget state="empty" title="Заявок нет" />)
    const empty = screen.getByTestId('mobile-state-empty')
    const picture = empty.querySelector('svg')
    expect(picture).not.toBeNull()
    expect(picture!.closest('[aria-hidden="true"]')).not.toBeNull()
  })

  it('shows an error with «Повторить»', () => {
    const onRetry = vi.fn()
    render(<MobileStateWidget state="error" onRetry={onRetry} />)
    const alert = screen.getByRole('alert')
    expect(alert).toHaveTextContent('Не удалось загрузить данные')
    fireEvent.click(within(alert).getByRole('button', { name: /Повторить/ }))
    expect(onRetry).toHaveBeenCalledTimes(1)
  })
})

describe('MobileCardFeedWidget', () => {
  function source(overrides: Partial<CardFeedSource<Vendor>>): CardFeedSource<Vendor> {
    return {
      items: VENDORS,
      loading: false,
      loadingMore: false,
      error: null,
      hasMore: false,
      sentinelRef: createRef<HTMLDivElement>(),
      reload: vi.fn(),
      loadMore: vi.fn(),
      ...overrides,
    }
  }

  function renderFeed(list: CardFeedSource<Vendor>) {
    return render(
      <MobileCardFeedWidget<Vendor>
        list={list}
        label="Поставщики"
        getKey={(v) => v.id}
        renderItem={(v) => <span>{v.name}</span>}
        empty={<p>Пусто</p>}
      />,
    )
  }

  it('renders the cards and «Загружаем ещё…» while the next page loads', () => {
    renderFeed(source({ hasMore: true, loadingMore: true }))
    const list = screen.getByRole('list', { name: 'Поставщики' })
    expect(within(list).getAllByRole('listitem')).toHaveLength(2)
    expect(screen.getByText('Загружаем ещё…')).toBeInTheDocument()
  })

  it('shows skeletons, the empty state and the error state of the first page', () => {
    const { unmount } = renderFeed(source({ items: [], loading: true }))
    expect(screen.getByRole('status', { name: 'Загрузка' })).toBeInTheDocument()
    unmount()

    const empty = renderFeed(source({ items: [] }))
    expect(screen.getByText('Пусто')).toBeInTheDocument()
    empty.unmount()

    const reload = vi.fn()
    renderFeed(source({ items: [], error: 'Ошибка запроса', reload }))
    fireEvent.click(screen.getByRole('button', { name: /Повторить/ }))
    expect(reload).toHaveBeenCalledTimes(1)
  })
})

describe('DesktopOnlyPage', () => {
  afterEach(() => {
    moduleAccess.loading = false
    moduleAccess.denied = new Set()
  })

  function renderStub() {
    return render(
      <MemoryRouter initialEntries={['/cash/expenses?wallet=3']}>
        <Routes>
          <Route path="/cash/expenses" element={<DesktopOnlyPage />} />
          <Route path="/" element={<div>Главный экран</div>} />
        </Routes>
      </MemoryRouter>,
    )
  }

  it('says the section is not available in the app, with no address and no copy button', () => {
    renderStub()
    expect(screen.getByRole('heading', { name: 'Раздел недоступен в приложении' })).toBeInTheDocument()
    expect(screen.queryByText(/компьютер/)).toBeNull()
    expect(screen.queryByText(/cash\/expenses/)).toBeNull()
    expect(screen.queryByRole('button', { name: /Скопировать ссылку/ })).toBeNull()
    expect(screen.getAllByRole('button')).toHaveLength(1)
  })

  it('leads to the start screen', () => {
    renderStub()
    fireEvent.click(screen.getByRole('button', { name: /На главный экран/ }))
    expect(screen.getByText('Главный экран')).toBeInTheDocument()
  })

  it('leads to the start screen without the requests module too', () => {
    moduleAccess.denied = new Set(['requests'])
    renderStub()
    fireEvent.click(screen.getByRole('button', { name: /На главный экран/ }))
    expect(screen.getByText('Главный экран')).toBeInTheDocument()
  })
})
