/** Keys hidden in admin CRUD modals — заданные на сервере при create/update. */
export const ADMIN_CRUD_SKIP_KEYS = new Set(['id', 'tenant', 'created_at', 'created_by', 'updated_at'])

export type AdminCrudPrimitiveType = 'string' | 'number' | 'boolean' | 'null'

export type AdminCrudDynamicField = {
  key: string
  type: AdminCrudPrimitiveType
  choices?: Array<{ label: string; value: string | number }>
}

export type AdminCrudFieldPlan = {
  fields: AdminCrudDynamicField[]
  initial: Record<string, unknown>
  nonEditable: Array<{ key: string; value: unknown }>
}

function isPrimitive(value: unknown): value is string | number | boolean | null {
  return (
    value === null ||
    typeof value === 'string' ||
    typeof value === 'number' ||
    typeof value === 'boolean'
  )
}

export function classifyPrimitive(value: string | number | boolean | null): AdminCrudPrimitiveType {
  if (value === null) return 'null'
  if (typeof value === 'boolean') return 'boolean'
  if (typeof value === 'number') return 'number'
  return 'string'
}

function blankInitial(kind: AdminCrudPrimitiveType): unknown {
  if (kind === 'boolean') return false
  if (kind === 'number') return undefined
  if (kind === 'null') return null
  return ''
}

/** План формы создания записи из образца строки списка (очищенные начальные значения). */
export function planAdminCreateFieldsFromRow(template: Record<string, unknown>): AdminCrudFieldPlan {
  const initial: Record<string, unknown> = {}
  const nonEditable: Array<{ key: string; value: unknown }> = []
  const primitiveKinds: Record<string, AdminCrudPrimitiveType> = {}

  for (const [key, value] of Object.entries(template)) {
    if (key === 'id' || ADMIN_CRUD_SKIP_KEYS.has(key)) continue
    if (!isPrimitive(value)) {
      nonEditable.push({ key, value })
      continue
    }
    const t = classifyPrimitive(value)
    primitiveKinds[key] = t
    initial[key] = blankInitial(t)
  }

  const fields: AdminCrudDynamicField[] = Object.keys(primitiveKinds)
    .sort((a, b) => a.localeCompare(b))
    .map((key) => ({ key, type: primitiveKinds[key] }))

  return { fields, initial, nonEditable }
}

/**
 * План формы редактирования из существующей строки: примитивы становятся
 * редактируемыми полями (с фактическими значениями как initial), остальное —
 * nonEditable. Та же логика, что и в админ-CRUD, вынесена для переиспользования
 * во встроенной правке прямо из списков.
 */
export function planAdminEditFieldsFromRow(row: Record<string, unknown>): AdminCrudFieldPlan {
  const initial: Record<string, unknown> = {}
  const nonEditable: Array<{ key: string; value: unknown }> = []

  for (const [key, value] of Object.entries(row)) {
    if (ADMIN_CRUD_SKIP_KEYS.has(key)) continue
    if (isPrimitive(value)) initial[key] = value
    else nonEditable.push({ key, value })
  }

  const fields: AdminCrudDynamicField[] = Object.entries(initial)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([key, value]) => ({ key, type: classifyPrimitive(value as string | number | boolean | null) }))

  return { fields, initial, nonEditable }
}

/** Парсит DRF metadata `actions.POST` в план формы создания (если структура узнаваемая). */
export function planAdminCreateFieldsFromOptionsPost(post: Record<string, unknown> | null | undefined): AdminCrudFieldPlan | null {
  if (!post || typeof post !== 'object') return null

  const fields: AdminCrudDynamicField[] = []
  const initial: Record<string, unknown> = {}

  const pushField = (key: string, f: AdminCrudDynamicField) => {
    fields.push(f)
    if (f.choices?.length)
      initial[key] = undefined
    else initial[key] = blankInitial(f.type)
  }

  for (const [key, raw] of Object.entries(post)) {
    if (ADMIN_CRUD_SKIP_KEYS.has(key)) continue
    if (!raw || typeof raw !== 'object') continue

    const d = raw as Record<string, unknown>
    if (d.read_only === true) continue

    const ty = typeof d.type === 'string' ? d.type.toLowerCase() : ''

    if (ty === 'nested object' || ty === 'list' || ty === 'multiples' || ty === 'serializer') continue

    if (ty === 'choice') {
      const choicesRaw = d.choices
      const choicesParsed: Array<{ label: string; value: string | number }> = []
      if (Array.isArray(choicesRaw)) {
        for (const c of choicesRaw) {
          if (c && typeof c === 'object' && 'value' in (c as object)) {
            const ch = c as { value?: unknown; display_name?: unknown }
            choicesParsed.push({
              value:
                typeof ch.value === 'string' || typeof ch.value === 'number'
                  ? ch.value
                  : String(ch.value ?? ''),
              label: typeof ch.display_name === 'string' ? ch.display_name : String(ch.value ?? ''),
            })
          }
        }
      }
      if (!choicesParsed.length) continue
      pushField(key, { key, type: 'string', choices: choicesParsed })
      continue
    }

    let prim: AdminCrudPrimitiveType = 'string'
    if (ty === 'boolean') prim = 'boolean'
    else if (ty === 'integer' || ty === 'float' || ty === 'decimal' || ty === 'number') prim = 'number'
    else if (ty.includes('nested')) continue

    pushField(key, { key, type: prim })
  }

  if (!fields.length) return null
  fields.sort((a, b) => a.key.localeCompare(b.key))
  return { fields, initial, nonEditable: [] }
}

export async function fetchAdminCrudPostSchema(endpoint: string, apiFetch: (url: string, init?: RequestInit) => Promise<Response>): Promise<Record<string, unknown> | null> {
  try {
    const res = await apiFetch(endpoint, { method: 'OPTIONS' })
    if (!res.ok) return null
    const json = (await res.json().catch(() => null)) as { actions?: { POST?: Record<string, unknown> } } | null
    const post = json?.actions?.POST
    if (!post || typeof post !== 'object') return null
    return post
  } catch {
    return null
  }
}
