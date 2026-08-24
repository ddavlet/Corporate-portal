# UI выплат по кассе — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a cashier record actual cash payouts against approved payroll-accrual lines directly from `PayrollDocumentDetailPage.tsx` (single-line or multi-line at once), and see disbursement progress at a glance from the `PayrollPage.tsx` document list — consuming the backend built in the employee-cutover-and-payouts-backend plan.

**Architecture:** `PayrollDocumentDetailPage.tsx` gets three new columns on the lines table (Выплачено / Остаток / a "Выплатить" action), row selection with a "Выплатить выбранным" bulk action, and an expandable per-line payout history — all backed by a single reusable `PayoutModal` that always calls the bulk payout endpoint (works identically for one line or several). `PayrollPage.tsx`'s document list gets a small disbursement-progress indicator next to the existing "Оплачено" tag, sourced from the document-level `paid_amount` field the backend plan already added.

**Tech Stack:** React + TypeScript, Ant Design.

**Spec:** `docs/superpowers/specs/2026-08-24-payroll-cash-payouts-design.md` (Часть 2, section "Фронтенд")

**Prerequisite:** `docs/superpowers/plans/2026-08-24-payroll-employee-cutover-and-payouts-backend.md` must be merged and deployed first — this plan consumes `PayrollDocumentDetailSerializer.{paid_amount,request_status}`, `PayrollLineSerializer.{employee,paid_amount,remaining_amount,payouts}`, and the `POST /api/payroll/lines/payouts/bulk/` endpoint it produces.

## Global Constraints

- Frontend-only — no backend changes in this plan.
- UI library is `antd`; icons from `@ant-design/icons`.
- No local test runner for the frontend per project rules — verify via `npx tsc --noEmit` and a manual smoke check (`run` skill or local dev server); `Vitest` runs in CI after push.
- The payout action is only ever enabled when the document's linked request is `PAYED` (`request_status === 'PAYED'`) — this mirrors the backend's own gate in `create_payroll_line_payout`, so the UI must not offer an action the API would reject anyway.

---

### Task 1: API client functions for payouts

**Files:**
- Modify: `frontend_v2/src/lib/api.ts`

**Interfaces:**
- Produces: `PayrollPayoutDto`, `createPayrollLinePayoutsBulk(payouts: { line_id: number; amount: number }[]): Promise<PayrollPayoutDto[]>` — consumed by Task 3.

- [ ] **Step 1: Add the payout DTO and bulk-create function**

In `frontend_v2/src/lib/api.ts`, add near the other payroll exports (after `createEmployee` from the previous plan):

```ts
export type PayrollPayoutDto = {
  id: number
  line_id: number
  amount: string | number
  created_at: string
  created_by: number | null
  created_by_full_name: string
}

export async function createPayrollLinePayoutsBulk(
  payouts: { line_id: number; amount: number }[],
): Promise<PayrollPayoutDto[]> {
  const res = await apiFetch('/api/payroll/lines/payouts/bulk/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ payouts }),
  })
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as PayrollPayoutDto[] | null
  return json ?? []
}
```

- [ ] **Step 2: Type-check**

Run: `cd frontend_v2 && npx tsc --noEmit`
Expected: no new errors.

- [ ] **Step 3: Commit**

```bash
git add frontend_v2/src/lib/api.ts
git commit -m "feat(payroll): add createPayrollLinePayoutsBulk API client function"
```

---

### Task 2: `PayrollPage.tsx` — disbursement progress in the document list

**Files:**
- Modify: `frontend_v2/src/ui/PayrollPage.tsx`

**Interfaces:**
- Consumes: `PayrollDocumentRow.paid_amount` (new backend field from the prerequisite plan) and the existing `total_sum` used elsewhere in this file's columns.

- [ ] **Step 1: Add `paid_amount` and `total_sum` to the row type and render a progress tag**

In `frontend_v2/src/ui/PayrollPage.tsx`, extend `PayrollDocumentRow`:

```ts
type PayrollDocumentRow = {
  id: number
  doc_id: string | null
  created_at: string
  total_sum: string | number
  paid_amount: string | number
  lines_count: number
  has_request?: boolean
  has_paid_request?: boolean
  matched_request_id?: number | null
}
```

Then, in the `columns` definition, find the render function that currently outputs the `<Tag color="blue">Есть заявка</Tag>` / `<Tag color="green">Оплачено</Tag>` tags (around line 421-425) and add a third tag right after them:

```tsx
            {r.has_request ? <Tag color="blue">Есть заявка</Tag> : null}
            {r.has_paid_request ? <Tag color="green">Оплачено</Tag> : null}
            {Number(r.paid_amount) > 0 ? (
              <Tag color={Number(r.paid_amount) >= Number(r.total_sum) ? 'green' : 'gold'}>
                Выплачено {Number(r.paid_amount).toLocaleString('ru-RU')} / {Number(r.total_sum).toLocaleString('ru-RU')}
              </Tag>
            ) : null}
            {r.matched_request_id ? (
              <Button type="link" size="small" onClick={() => navigate(`/requests/${r.matched_request_id}`)}>
                №{r.matched_request_id}
              </Button>
```

(This keeps the exact surrounding JSX structure — only the new `Tag` block is inserted between the existing `has_paid_request` tag and the `matched_request_id` button.)

- [ ] **Step 2: Type-check**

Run: `cd frontend_v2 && npx tsc --noEmit`
Expected: no new errors.

- [ ] **Step 3: Manual smoke check**

Using the `run` skill or local dev server: open the payroll documents list, confirm a document with recorded payouts (created via Task 4 below, or via the API directly) shows a "Выплачено X / Y" tag, colored gold while partial and green once fully paid; a document with no payouts shows no such tag.

- [ ] **Step 4: Commit**

```bash
git add frontend_v2/src/ui/PayrollPage.tsx
git commit -m "feat(payroll): show disbursement progress tag in the document list"
```

---

### Task 3: Reusable `PayoutModal`

**Files:**
- Create: `frontend_v2/src/ui/PayrollPayoutModal.tsx`

**Interfaces:**
- Consumes: `createPayrollLinePayoutsBulk` (Task 1).
- Produces: `export function PayrollPayoutModal(props)` — consumed by Task 4. Always calls the bulk endpoint, whether given one line or several, so single-line and multi-line payout share one code path.

- [ ] **Step 1: Create the modal**

Create `frontend_v2/src/ui/PayrollPayoutModal.tsx`:

```tsx
import { useEffect, useState } from 'react'
import { InputNumber, Modal, Space, Typography, message } from 'antd'
import { createPayrollLinePayoutsBulk } from '../lib/api'

export type PayoutTarget = {
  id: number
  employeeFullName: string
  remainingAmount: number
}

export function PayrollPayoutModal({
  open,
  targets,
  onClose,
  onDone,
}: {
  open: boolean
  targets: PayoutTarget[]
  onClose: () => void
  onDone: () => void
}) {
  const [amounts, setAmounts] = useState<Record<number, number>>({})
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!open) return
    const initial: Record<number, number> = {}
    for (const t of targets) initial[t.id] = t.remainingAmount
    setAmounts(initial)
  }, [open, targets])

  const onSubmit = async () => {
    const payouts = targets
      .map((t) => ({ line_id: t.id, amount: amounts[t.id] ?? 0 }))
      .filter((p) => p.amount > 0)
    if (payouts.length === 0) {
      message.error('Укажите сумму хотя бы для одной строки')
      return
    }
    setSaving(true)
    try {
      await createPayrollLinePayoutsBulk(payouts)
      message.success(payouts.length > 1 ? 'Выплаты проведены' : 'Выплата проведена')
      onDone()
      onClose()
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : 'Ошибка выплаты')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      title="Выплатить по кассе"
      open={open}
      onCancel={onClose}
      onOk={() => void onSubmit()}
      confirmLoading={saving}
      okText="Выплатить"
      destroyOnClose
    >
      <Space direction="vertical" style={{ display: 'flex' }} size={12}>
        {targets.map((t) => (
          <div key={t.id} style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <Typography.Text style={{ width: 200, flexShrink: 0 }}>{t.employeeFullName}</Typography.Text>
            <InputNumber
              min={0}
              max={t.remainingAmount}
              value={amounts[t.id] ?? 0}
              onChange={(v) => setAmounts((prev) => ({ ...prev, [t.id]: v ?? 0 }))}
              style={{ width: 160 }}
            />
            <Typography.Text type="secondary">
              из {t.remainingAmount.toLocaleString('ru-RU')}
            </Typography.Text>
          </div>
        ))}
      </Space>
    </Modal>
  )
}
```

- [ ] **Step 2: Type-check**

Run: `cd frontend_v2 && npx tsc --noEmit`
Expected: no new errors.

- [ ] **Step 3: Commit**

```bash
git add frontend_v2/src/ui/PayrollPayoutModal.tsx
git commit -m "feat(payroll): add reusable payout modal for single/bulk cash payouts"
```

---

### Task 4: Wire payouts into `PayrollDocumentDetailPage.tsx`

**Files:**
- Modify: `frontend_v2/src/ui/PayrollDocumentDetailPage.tsx` (full rewrite — the file is currently 132 lines; the version below is the complete replacement)

**Interfaces:**
- Consumes: `PayrollPayoutModal`, `PayoutTarget` (Task 3).

- [ ] **Step 1: Replace the file**

Replace the full content of `frontend_v2/src/ui/PayrollDocumentDetailPage.tsx` with:

```tsx
import { useCallback, useEffect, useState } from 'react'
import { Alert, Button, Card, Descriptions, Skeleton, Space, Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useNavigate, useParams } from 'react-router-dom'
import { RequestReturnBackButton } from './requests/RequestReturnBackButton'
import { PayrollPayoutModal, type PayoutTarget } from './PayrollPayoutModal'
import { apiFetch } from '../lib/api'

type EmployeeRef = {
  id: number
  full_name: string
}

type PayoutEntry = {
  id: number
  amount: string | number
  created_at: string
  created_by_full_name: string
}

type PayrollLineRow = {
  id: number
  line_no: number
  employee: EmployeeRef
  item: string
  description?: string | null
  sum: string | number
  days_plan: number
  days_fact: number
  period_start: string
  period_end: string
  approval: boolean
  paid_amount: string | number
  remaining_amount: string | number
  payouts: PayoutEntry[]
}

type PayrollDocumentDetail = {
  id: number
  doc_id: string | null
  created_at: string
  total_sum: string | number
  paid_amount: string | number
  request_status: string | null
  lines: PayrollLineRow[]
}

const dateFmt = new Intl.DateTimeFormat('ru-RU', {
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  timeZone: 'Asia/Tashkent',
})

function formatDate(value?: string | null): string {
  if (!value) return '-'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return '-'
  return dateFmt.format(parsed)
}

function formatMoney(value: string | number): string {
  return Number(value).toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

export function PayrollDocumentDetailPage() {
  const navigate = useNavigate()
  const { id } = useParams<{ id: string }>()
  const [detail, setDetail] = useState<PayrollDocumentDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedLineIds, setSelectedLineIds] = useState<number[]>([])
  const [payoutTargets, setPayoutTargets] = useState<PayoutTarget[] | null>(null)

  const load = useCallback(async () => {
    if (!id) {
      setError('Не указан id документа.')
      setLoading(false)
      return
    }
    setLoading(true)
    setError(null)
    try {
      const res = await apiFetch(`/api/payroll/documents/${id}/`)
      const json = (await res.json().catch(() => null)) as PayrollDocumentDetail | null
      if (!res.ok) {
        throw new Error(typeof json === 'object' && json ? JSON.stringify(json) : `HTTP ${res.status}`)
      }
      setDetail(json)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Ошибка загрузки')
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => {
    void load()
  }, [load])

  const canPayout = detail?.request_status === 'PAYED'

  const openPayoutFor = (lines: PayrollLineRow[]) => {
    setPayoutTargets(
      lines
        .filter((l) => Number(l.remaining_amount) > 0)
        .map((l) => ({
          id: l.id,
          employeeFullName: l.employee.full_name,
          remainingAmount: Number(l.remaining_amount),
        })),
    )
  }

  const lineColumns: ColumnsType<PayrollLineRow> = [
    { title: '№', dataIndex: 'line_no', width: 56 },
    { title: 'Сотрудник', key: 'employee', render: (_, r) => r.employee.full_name },
    { title: 'Вид', dataIndex: 'item', width: 140 },
    { title: 'Сумма', dataIndex: 'sum', width: 130, render: (v) => formatMoney(v) },
    { title: 'Выплачено', dataIndex: 'paid_amount', width: 130, render: (v) => formatMoney(v) },
    { title: 'Остаток', dataIndex: 'remaining_amount', width: 130, render: (v) => formatMoney(v) },
    { title: 'Дни план', dataIndex: 'days_plan', width: 88 },
    { title: 'Дни факт', dataIndex: 'days_fact', width: 88 },
    {
      title: 'Период',
      key: 'period',
      width: 200,
      render: (_, r) => `${formatDate(r.period_start)} — ${formatDate(r.period_end)}`,
    },
    {
      title: 'Подтверждено',
      dataIndex: 'approval',
      width: 120,
      render: (v: boolean) => (v ? 'Да' : 'Нет'),
    },
    {
      title: '',
      key: 'action',
      width: 120,
      render: (_, r) =>
        canPayout && Number(r.remaining_amount) > 0 ? (
          <Button size="small" type="primary" onClick={() => openPayoutFor([r])}>
            Выплатить
          </Button>
        ) : null,
    },
  ]

  return (
    <Card>
      <Space direction="vertical" size={12} style={{ display: 'flex' }}>
        <RequestReturnBackButton fallbackPath="/payroll" fallbackLabel="Назад к списку" />
        {loading ? <Skeleton active /> : null}
        {error ? <Alert type="error" showIcon message={error} /> : null}
        {!loading && !error && detail ? (
          <>
            <Typography.Title level={4} style={{ marginTop: 0 }}>
              Начисление ЗП: {detail.doc_id || 'без номера (создано в портале)'}
            </Typography.Title>
            <Descriptions bordered size="small" column={2}>
              <Descriptions.Item label="Итого">{formatMoney(detail.total_sum)}</Descriptions.Item>
              <Descriptions.Item label="Выплачено">
                {formatMoney(detail.paid_amount)}{' '}
                {detail.request_status ? (
                  <Tag color={detail.request_status === 'PAYED' ? 'green' : 'default'} style={{ marginLeft: 8 }}>
                    Заявка: {detail.request_status}
                  </Tag>
                ) : null}
              </Descriptions.Item>
              <Descriptions.Item label="Строк">{detail.lines?.length ?? 0}</Descriptions.Item>
              <Descriptions.Item label="Создан">{formatDate(detail.created_at)}</Descriptions.Item>
            </Descriptions>
            <Space align="center" style={{ justifyContent: 'space-between', display: 'flex' }}>
              <Typography.Title level={5} style={{ margin: 0 }}>
                Строки
              </Typography.Title>
              {canPayout ? (
                <Button
                  disabled={selectedLineIds.length === 0}
                  onClick={() => openPayoutFor(detail.lines.filter((l) => selectedLineIds.includes(l.id)))}
                >
                  Выплатить выбранным
                </Button>
              ) : null}
            </Space>
            <Table<PayrollLineRow>
              rowKey="id"
              size="small"
              columns={lineColumns}
              dataSource={detail.lines || []}
              pagination={false}
              rowSelection={
                canPayout
                  ? {
                      selectedRowKeys: selectedLineIds,
                      onChange: (keys) => setSelectedLineIds(keys as number[]),
                      getCheckboxProps: (record) => ({ disabled: Number(record.remaining_amount) <= 0 }),
                    }
                  : undefined
              }
              expandable={{
                expandedRowRender: (record) => (
                  <Table<PayoutEntry>
                    size="small"
                    rowKey="id"
                    pagination={false}
                    dataSource={record.payouts}
                    locale={{ emptyText: 'Выплат ещё не было' }}
                    columns={[
                      { title: 'Дата', dataIndex: 'created_at', render: (v) => formatDate(v) },
                      { title: 'Сумма', dataIndex: 'amount', render: (v) => formatMoney(v) },
                      { title: 'Кто провёл', dataIndex: 'created_by_full_name' },
                    ]}
                  />
                ),
                rowExpandable: (record) => record.payouts.length > 0,
              }}
            />
          </>
        ) : null}
      </Space>
      <PayrollPayoutModal
        open={payoutTargets !== null}
        targets={payoutTargets ?? []}
        onClose={() => setPayoutTargets(null)}
        onDone={() => {
          setSelectedLineIds([])
          void load()
        }}
      />
    </Card>
  )
}
```

Note this file no longer references `navigate` directly except via the existing `RequestReturnBackButton` import — the `useNavigate` import and `navigate` variable are kept because `RequestReturnBackButton` may use navigation internally via its own props (`fallbackPath`); if `npx tsc --noEmit` in Step 2 reports `navigate` as unused, remove the `const navigate = useNavigate()` line and the `useNavigate` import (this file's original version already had this exact same unused-variable risk pattern, so check against the original before assuming either way).

- [ ] **Step 2: Type-check**

Run: `cd frontend_v2 && npx tsc --noEmit`
Expected: no new errors. If `navigate` is reported unused, remove it per the note above.

- [ ] **Step 3: Manual smoke check**

Using the `run` skill or local dev server, with a payroll document whose linked request is `PAYED` (created via the prerequisite plan's flow — approve a payroll request through to `PAYED`, or set it directly in a test tenant):
1. Open the document detail page, confirm "Выплатить" appears per line and "Выплачено"/"Остаток" columns show `0` / full amount initially.
2. Click "Выплатить" on one line, submit a partial amount, confirm the line's "Выплачено"/"Остаток" update after reload and the row's history (expand arrow) shows the new payout with a real name in "Кто провёл".
3. Select two lines via checkboxes, click "Выплатить выбранным", submit both, confirm both update.
4. Try to submit an amount larger than a line's remaining amount — confirm the `InputNumber`'s `max` prevents entering more than the remainder, and that a value at exactly the remainder (paying off the line fully) removes that line's checkbox eligibility (row disabled) afterward.
5. Open a document whose request is **not** `PAYED` (or has no linked request at all — `request_status` is `null`), confirm no "Выплатить" buttons, no row selection, and no "Выплатить выбранным" button appear.

- [ ] **Step 4: Commit**

```bash
git add frontend_v2/src/ui/PayrollDocumentDetailPage.tsx
git commit -m "feat(payroll): add cash payout UI to the document detail page"
```

---

## Self-Review Notes

- Spec coverage: implements every bullet under Часть 2 → Фронтенд in the spec — Descriptions "Выплачено", three new line columns, row selection + bulk action, expandable payout history (`PayrollDocumentDetailPage.tsx`), and the list-level progress tag (`PayrollPage.tsx`). The requests-module UI is untouched, per the earlier decision to limit this to the two payroll pages.
- No placeholders: `PayrollDocumentDetailPage.tsx` is given as a full file replacement, not a diff description, since the change touches nearly every part of the file (types, columns, layout).
- Type consistency: `PayoutTarget` (`{ id, employeeFullName, remainingAmount }`) is defined once in `PayrollPayoutModal.tsx` (Task 3) and imported, not redefined, in `PayrollDocumentDetailPage.tsx` (Task 4). `PayrollPayoutDto.created_by_full_name` (Task 1) matches the field name the prerequisite backend plan's `PayrollPayoutSerializer` actually produces (confirmed against that plan's Task 8, Step 2 after its self-review fix).
