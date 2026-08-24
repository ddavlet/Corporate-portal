# Перенос настроек начислений ЗП в /app/settings — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the "Формат номера ведомости (doc_id)" and "Настройки начислений" sections out of the `PayrollPage.tsx` header into a dedicated settings page under `/app/settings`, following the same `settingsModules.tsx` + dedicated-page pattern used by every other module's settings.

**Architecture:** Pure frontend relocation. Two existing components (`PayrollDocIdFormatSection`, `PayrollSettingsSection`) move verbatim from `PayrollPage.tsx` into a new `frontend_v2/src/ui/settings/PayrollSettingsPage.tsx`. A new settings group "Заработная плата" and a module card are registered in `settingsModules.tsx`, a route is added in `App.tsx`, and access is gated the same way as `pnl-report-config`/`cashflow-report-config`/`tasks-config` (admin only) in `SettingsPage.tsx`. No backend changes — the same existing API endpoints (`/api/tenant/payroll-doc-id-format/`, `/api/tenant/payroll-settings/`) are reused unchanged.

**Tech Stack:** React + TypeScript, Ant Design (antd), React Router.

**Spec:** `docs/superpowers/specs/2026-08-24-payroll-cash-payouts-design.md` (Часть 3: "Настройки — перенос в `/app/settings`")

## Global Constraints

- No backend changes in this plan — frontend only.
- Follow the existing settings-module pattern exactly (`frontend_v2/src/settings/settingsModules.tsx` + `frontend_v2/src/ui/settings/*SettingsPage.tsx` + route in `App.tsx` + access line in `SettingsPage.tsx`). Do not invent a new pattern.
- UI library is `antd`; icons from `@ant-design/icons`.
- This is frontend-only — no local test runner exists for this per project rules; verification is via `npm run build`/`tsc` type-checking (see Task 2, Step 4) since there's no local dev-server browser check required by CLAUDE.md for a pure relocation with no behavior change. Full CI (`Vitest`) runs after push, per project workflow.

---

### Task 1: Create `PayrollSettingsPage.tsx` with the two relocated sections

**Files:**
- Create: `frontend_v2/src/ui/settings/PayrollSettingsPage.tsx`
- Modify: `frontend_v2/src/ui/PayrollPage.tsx:1-36` (imports), `frontend_v2/src/ui/PayrollPage.tsx:67-217` (remove the two section components), `frontend_v2/src/ui/PayrollPage.tsx:445-448` (remove their render calls)

**Interfaces:**
- Consumes: existing `frontend_v2/src/lib/api.ts` exports — `getTenantPayrollDocIdFormat`, `updateTenantPayrollDocIdFormat`, `getTenantPayrollSettings`, `updateTenantPayrollSettings` (all already implemented, unchanged).
- Produces: `export function PayrollSettingsPage()` from `frontend_v2/src/ui/settings/PayrollSettingsPage.tsx` — consumed by Task 2 (route registration).

- [ ] **Step 1: Create the new file with both sections moved verbatim**

Create `frontend_v2/src/ui/settings/PayrollSettingsPage.tsx`:

```tsx
import { useState } from 'react'
import { Button, Card, Checkbox, Form, Input, InputNumber, Typography, message } from 'antd'
import {
  getTenantPayrollDocIdFormat,
  getTenantPayrollSettings,
  updateTenantPayrollDocIdFormat,
  updateTenantPayrollSettings,
} from '../../lib/api'
import { useEffect } from 'react'

function previewPayrollDocId(prefix: string, digitWidth: number, sampleNumeric: number): string {
  const w = Number.isFinite(digitWidth) ? Math.min(32, Math.max(1, Math.floor(digitWidth))) : 9
  const core = String(Math.trunc(sampleNumeric)).padStart(w, '0')
  return `${prefix}${core}`
}

function PayrollDocIdFormatSection() {
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [hidden, setHidden] = useState(false)
  const [form] = Form.useForm<{
    payroll_doc_id_prefix: string
    payroll_doc_id_digit_width: number
  }>()
  const prefixWatch = Form.useWatch('payroll_doc_id_prefix', form)
  const widthWatch = Form.useWatch('payroll_doc_id_digit_width', form)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setLoading(true)
      try {
        const data = await getTenantPayrollDocIdFormat()
        if (cancelled) return
        form.setFieldsValue({
          payroll_doc_id_prefix: data.payroll_doc_id_prefix ?? '',
          payroll_doc_id_digit_width: data.payroll_doc_id_digit_width ?? 9,
        })
        setHidden(false)
      } catch {
        if (!cancelled) setHidden(true)
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [form])

  if (hidden) return null

  const p = typeof prefixWatch === 'string' ? prefixWatch : ''
  const dw = typeof widthWatch === 'number' ? widthWatch : 9
  const preview = previewPayrollDocId(p, dw, 459)

  const onSave = async () => {
    try {
      const v = await form.validateFields()
      setSaving(true)
      await updateTenantPayrollDocIdFormat({
        payroll_doc_id_prefix: v.payroll_doc_id_prefix.trim(),
        payroll_doc_id_digit_width: v.payroll_doc_id_digit_width,
      })
      message.success('Сохранено')
    } catch (e: unknown) {
      if (e && typeof e === 'object' && 'errorFields' in e) return
      message.error(e instanceof Error ? e.message : 'Ошибка сохранения')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card title="Формат номера ведомости (doc_id)" style={{ marginBottom: 16 }} loading={loading}>
      <Typography.Paragraph type="secondary">
        Привязка заявки типа «Начисление ЗП»: можно ввести короткий номер (например{' '}
        <Typography.Text code>459</Typography.Text>), система найдёт документ по полному <Typography.Text code>doc_id</Typography.Text>.
      </Typography.Paragraph>
      <Form form={form} layout="vertical" disabled={loading}>
        <Form.Item
          label="Префикс перед номером"
          name="payroll_doc_id_prefix"
          rules={[{ max: 32, message: 'Не длиннее 32 символов' }]}
        >
          <Input placeholder="Например: 1- или пусто" allowClear />
        </Form.Item>
        <Form.Item
          label="Числовая часть: знаков всего"
          name="payroll_doc_id_digit_width"
          rules={[{ required: true }]}
        >
          <InputNumber min={1} max={32} style={{ width: '100%' }} />
        </Form.Item>
      </Form>
      <Typography.Paragraph style={{ marginBottom: 16 }}>
        Пример: ввод <Typography.Text code>459</Typography.Text> совпадает с ведомостью{' '}
        <Typography.Text code>{preview}</Typography.Text>.
      </Typography.Paragraph>
      <Button type="primary" onClick={() => void onSave()} loading={saving} disabled={loading}>
        Сохранить формат
      </Button>
    </Card>
  )
}

function PayrollSettingsSection() {
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [hidden, setHidden] = useState(false)
  const [enabled, setEnabled] = useState(false)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setLoading(true)
      try {
        const data = await getTenantPayrollSettings()
        if (cancelled) return
        setEnabled(data.create_payment_request_on_payroll_accrual)
        setHidden(false)
      } catch {
        if (!cancelled) setHidden(true)
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  if (hidden) return null

  const onToggle = async (checked: boolean) => {
    const prev = enabled
    setEnabled(checked)
    setSaving(true)
    try {
      await updateTenantPayrollSettings({ create_payment_request_on_payroll_accrual: checked })
      message.success('Сохранено')
    } catch (e: unknown) {
      setEnabled(prev)
      message.error(e instanceof Error ? e.message : 'Ошибка сохранения')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card title="Настройки начислений" style={{ marginBottom: 16 }} loading={loading}>
      <Checkbox checked={enabled} disabled={loading || saving} onChange={(e) => void onToggle(e.target.checked)}>
        Создавать заявку на оплату при создании начисления
      </Checkbox>
      <Typography.Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0 }}>
        Применяется и к начислениям, созданным в портале, и к загруженным через n8n — на сумму всего документа
        создаётся одна заявка.
      </Typography.Paragraph>
    </Card>
  )
}

export function PayrollSettingsPage() {
  return (
    <>
      <PayrollDocIdFormatSection />
      <PayrollSettingsSection />
    </>
  )
}
```

Note: the `useEffect` import is deliberately listed after the antd import in the example above only for readability here — write it as a normal combined import line: `import { useEffect, useState } from 'react'` at the top instead of two separate `react` imports.

- [ ] **Step 2: Remove the two sections and their render calls from `PayrollPage.tsx`**

In `frontend_v2/src/ui/PayrollPage.tsx`:
1. Delete the `previewPayrollDocId` function (lines 67-71 in the current file).
2. Delete the `PayrollDocIdFormatSection` function (lines 73-161).
3. Delete the `PayrollSettingsSection` function (lines 163-217).
4. Remove the two render calls in the returned JSX:
   ```tsx
   <PayrollDocIdFormatSection />
   <PayrollSettingsSection />
   ```
   so the `return (...)` block starts directly with `<Card>` (the "Начисления ЗП" list card) instead of these two lines followed by `<Card>`.
5. Update the top import block: remove `Checkbox` from the antd import list (no longer used anywhere else in this file), and remove `getTenantPayrollDocIdFormat`, `getTenantPayrollSettings`, `updateTenantPayrollDocIdFormat`, `updateTenantPayrollSettings` from the `../lib/api` import list (keep `createPayrollDocument` and `type PayrollLineCreatePayload`, which are still used by `CreatePayrollDocumentModal`).

- [ ] **Step 3: Verify no remaining references**

Run: `grep -n "PayrollDocIdFormatSection\|PayrollSettingsSection\|previewPayrollDocId\|Checkbox\|getTenantPayrollDocIdFormat\|getTenantPayrollSettings\|updateTenantPayrollDocIdFormat\|updateTenantPayrollSettings" frontend_v2/src/ui/PayrollPage.tsx`

Expected: no output (all removed).

- [ ] **Step 4: Type-check**

Run: `cd frontend_v2 && npx tsc --noEmit`
Expected: no new errors introduced by this change (pre-existing unrelated errors, if any, are out of scope).

- [ ] **Step 5: Commit**

```bash
git add frontend_v2/src/ui/settings/PayrollSettingsPage.tsx frontend_v2/src/ui/PayrollPage.tsx
git commit -m "refactor(payroll): move payroll settings sections into settings/PayrollSettingsPage"
```

---

### Task 2: Register the new settings group, card, route and access check

**Files:**
- Modify: `frontend_v2/src/settings/settingsModules.tsx`
- Modify: `frontend_v2/src/routes/App.tsx`
- Modify: `frontend_v2/src/ui/SettingsPage.tsx`

**Interfaces:**
- Consumes: `PayrollSettingsPage` from `frontend_v2/src/ui/settings/PayrollSettingsPage.tsx` (produced by Task 1).
- Produces: route `/settings/payroll-config`, reachable from the "Заработная плата" group card in `/app/settings`.

- [ ] **Step 1: Add the new group and module card**

In `frontend_v2/src/settings/settingsModules.tsx`:

1. Add `DollarOutlined` to the icon import at the top:
   ```tsx
   import { BarChartOutlined, BankOutlined, CheckSquareOutlined, DollarOutlined, FileTextOutlined, MessageOutlined, SettingOutlined, ShopOutlined, TeamOutlined } from '@ant-design/icons'
   ```
2. Append a new entry to `SETTINGS_GROUPS` (after the `finance` group):
   ```tsx
   {
     key: 'payroll',
     label: 'Заработная плата',
     description: 'Начисления, выплаты по кассе и справочник сотрудников.',
     icon: <DollarOutlined />,
   },
   ```
3. Append a new entry to `SETTINGS_MODULES` (after `cash-registers`):
   ```tsx
   {
     key: 'payroll-config',
     title: 'Начисления ЗП',
     description: 'Формат номера документа, автосоздание заявки на оплату, справочник сотрудников.',
     path: '/settings/payroll-config',
     icon: <DollarOutlined />,
     group: 'payroll',
   },
   ```

- [ ] **Step 2: Register the route**

In `frontend_v2/src/routes/App.tsx`:
1. Add the import next to the other settings-page imports (near `import { PnlReportSettingsPage } from '../ui/settings/PnlReportSettingsPage'`):
   ```tsx
   import { PayrollSettingsPage } from '../ui/settings/PayrollSettingsPage'
   ```
2. Add the route next to the other `settings/*-config` routes:
   ```tsx
   <Route path="settings/payroll-config" element={<PayrollSettingsPage />} />
   ```

- [ ] **Step 3: Gate access to admin only**

In `frontend_v2/src/ui/SettingsPage.tsx`, inside the `check` function in `moduleAccessMap` (around the existing `if (m.path === '/settings/pnl-report-config' || ...)` line), add `/settings/payroll-config` to that same admin-only branch:
```tsx
if (m.path === '/settings/pnl-report-config' || m.path === '/settings/cashflow-report-config' || m.path === '/settings/payroll-config') return access.can_manage_tenant_settings
```

- [ ] **Step 4: Type-check**

Run: `cd frontend_v2 && npx tsc --noEmit`
Expected: no new errors.

- [ ] **Step 5: Manual smoke check**

Since this changes routing/navigation (not covered by an automated test in this codebase), do a manual check using the `run` skill or local dev server: navigate to `/app/settings`, confirm a "Заработная плата" group card appears (admin user), open it, confirm "Начисления ЗП" card is there, click through to `/settings/payroll-config`, confirm both sections render and the doc-id-format save / toggle still work (same as they did in the old `PayrollPage.tsx` header). Confirm `/app/payroll` (or wherever `PayrollPage` is routed) no longer shows either settings section above the "Начисления ЗП" list.

- [ ] **Step 6: Commit**

```bash
git add frontend_v2/src/settings/settingsModules.tsx frontend_v2/src/routes/App.tsx frontend_v2/src/ui/SettingsPage.tsx
git commit -m "feat(settings): add Заработная плата settings group with payroll-config page"
```

---

## Self-Review Notes

- Spec coverage: implements all of "Часть 3" of the spec (relocate both sections, new group "Заработная плата", route, admin-only access). The employee-directory section mentioned in Часть 3 as living on the same page is deliberately **not** added here — `Employee` doesn't exist yet; it is added to this same `PayrollSettingsPage.tsx` file by the Phase-C cutover plan.
- No placeholders: both moved components are given in full; every edit site is an exact line range from the current file.
- Type consistency: `PayrollSettingsPage` export name matches what Task 2 imports; DTO types (`TenantPayrollDocIdFormatDto`, `TenantPayrollSettingsDto`) are unchanged, reused from `lib/api.ts` as-is.
