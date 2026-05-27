# Task Management Module — Implementation Plan

**Date:** 2026-05-25
**Approach:** Native Django module inside `backend_v2/apps/modules/tasks/` — no separate service, no Docker
**Design principle:** OCP (Open/Closed) — extend by adding new classes, never by editing existing logic
**Frontend:** React + Ant Design inside `frontend_v2/src/ui/tasks/`

---

## 1. Goals (Recap)

Based on the requirements gathered:

| Requirement | Decision |
|---|---|
| Auto-create tasks on approval/payment events | Yes — multiple trigger points |
| Auto-close tasks when the corresponding action happens | Yes — atomically with the event |
| Manual task creation | Yes — through UI and MCP |
| Task statuses | `new`, `in_progress`, `done` (3 statuses, intentionally minimal) |
| Task assignment | One task = one assignee (no multi-user tasks) |
| Comments | Yes — directors and admins can comment on other users' tasks |
| Permissions | Users see own tasks only; admins and directors see all tenant tasks |
| Display rule | Show only **last 3 done tasks** per user to avoid clutter |
| Notifications | Daily 9:00 AM Tashkent time Telegram digest with task summary + webapp button |
| MCP access | Yes — task tools exposed to Claude/AI via existing FastMCP server |
| Tech stack | Django/DRF backend, React + Ant Design frontend |

---

## 2. Roles & Permissions

Using the existing role system from `apps/tenants/models.py` (`TenantUserRole`):

| Role | Can see | Can create | Can comment on others' tasks | Can change status of others' tasks |
|---|---|---|---|---|
| `admin` | All tenant tasks | Yes | Yes | Yes |
| `director` | All tenant tasks | Yes | Yes | Yes |
| All other roles (requester, approver, cashier, accountant, investor) | Own tasks only | Yes (for self) | No | No (only own) |

Permission classes implemented in `apps/modules/tasks/permissions.py` following the OCP pattern.

---

## 3. Data Model

### 3.1 `Task` model

| Field | Type | Description |
|---|---|---|
| `id` | BigAutoField | Primary key |
| `tenant` | FK → Tenant | Multi-tenancy isolation |
| `assignee` | FK → User | The single person responsible (one task = one person) |
| `created_by` | FK → User (nullable) | Null when auto-created by system; set when created manually |
| `title` | CharField(255) | Short task title |
| `description` | TextField | Optional detailed description |
| `status` | CharField(16) | One of: `new`, `in_progress`, `done` |
| `source_type` | CharField(32, nullable) | Auto-trigger source: `approval_step`, `request_approved`, `payment_verify`, `request_rejected`, `escalation`, `manual` |
| `source_approval` | FK → Approval (nullable) | If task came from an approval step |
| `source_request` | FK → Request (nullable) | If task came from a request event |
| `source_expense_type` | CharField (nullable) | `cash`, `bank`, `card`, or null |
| `source_expense_id` | BigInt (nullable) | ID of the expense (loose link — expenses live in different tables) |
| `created_at` | DateTime | Auto-set |
| `updated_at` | DateTime | Auto-updated |
| `completed_at` | DateTime (nullable) | Set when status moves to `done` |

**Why explicit FK fields instead of GenericForeignKey:**
Querying by source is fast (indexed FK), the admin UI is clean, and the API contract is explicit. The downside (one nullable FK per source type) is small because we have a fixed, known set of sources.

**Indexes:**
- `(tenant, assignee, status)` — main "my tasks" query
- `(tenant, status, completed_at)` — for "last 3 done tasks" cutoff
- `(source_approval)` — for auto-close lookup

### 3.2 `TaskComment` model

| Field | Type | Description |
|---|---|---|
| `id` | BigAutoField | Primary key |
| `task` | FK → Task | Parent task |
| `author` | FK → User | Who wrote the comment |
| `body` | TextField | Comment content |
| `created_at` | DateTime | Auto-set |

Comments are append-only (no edit/delete in v1 — simpler and avoids audit complications).

---

## 4. Module Structure (OCP-Compliant)

```
backend_v2/apps/modules/tasks/
├── apps.py
├── models.py                      # Task, TaskComment
├── serializers.py                 # DRF serializers
├── views.py                       # API endpoints (thin)
├── urls.py                        # routing
├── permissions.py                 # OCP-style permission classes
├── admin.py
├── migrations/
│
├── services/                      # Business logic (called by views, signals, MCP)
│   ├── task_service.py            # create/update/close (the only place that mutates Task)
│   └── comment_service.py
│
├── triggers/                      # OCP: one class per auto-trigger event
│   ├── base.py                    # AbstractTaskTrigger interface
│   ├── registry.py                # TaskTriggerRegistry — dispatches events
│   ├── approval_step_activated.py # creates task when a step becomes active for a user
│   ├── approval_step_decided.py   # closes task when approval is decided
│   ├── request_approved.py        # creates "Process payment" task
│   ├── payment_confirmed.py       # creates "Verify transaction" task + closes payment task
│   ├── request_rejected.py        # creates "Notify requester" task
│   └── escalation.py              # creates escalation task when step is pending too long
│
├── querysets/                     # OCP: one class per scoping rule
│   ├── base.py                    # AbstractTaskScope
│   ├── own_tasks.py               # OwnTasksScope (regular users)
│   └── tenant_tasks.py            # TenantTasksScope (admin/director)
│
└── notifications/                 # OCP: one class per notification channel
    ├── base.py                    # AbstractNotificationChannel
    ├── telegram_digest.py         # TelegramDailyDigestChannel
    └── celery_tasks.py            # Celery beat schedule entry point
```

### 4.1 Why this structure satisfies OCP

| Concern | OCP solution |
|---|---|
| Adding a new auto-trigger | Add a new file in `triggers/` and register it — no edits to existing triggers |
| Adding a new notification channel (email, in-app, push) | Add a new class in `notifications/` implementing `AbstractNotificationChannel` |
| Adding a new permission scope (e.g., team-leads see their team only) | Add a new scope class in `querysets/` — no `if role == 'X'` chains in views |
| Adding a new task status | Add to `STATUS_CHOICES` + a transition handler class — no scattered `elif` blocks |

**Forbidden pattern:** `if event_type == "request_approved": ... elif event_type == "payment_confirmed": ...`
**Required pattern:** registry of trigger classes; dispatch by lookup.

---

## 5. Auto-Trigger Specifications

These are the system events that automatically create or close tasks. Each is implemented as a separate trigger class in `apps/modules/tasks/triggers/`.

### 5.1 ApprovalStepActivatedTrigger

**Fires when:** A new approval step becomes active for a user (i.e., the `Approval` row's step matches the request's current active step and `decision = pending`).

**Action:** Creates a `Task` for the approver.
- `assignee` = `Approval.approver_user`
- `title` = "Approve request #{request.id} — {request.title or vendor name}"
- `source_type` = `approval_step`
- `source_approval` = the Approval row
- `source_request` = the Request

**Hook point:** Inside `route_request_approvals()` in `approval_workflow.py`, right after `dispatch_pending_approvals(...)` runs. Atomically created in the same transaction.

### 5.2 ApprovalStepDecidedTrigger (auto-close)

**Fires when:** User approves or rejects an approval step.

**Action:** Closes the corresponding `Task` immediately (sets status to `done`, sets `completed_at`).
- Lookup: `Task.objects.filter(source_approval=approval, status__in=[new, in_progress])`

**Hook point:** Inside `confirm_approval_by_id()` in `approval_workflow.py`, in the same transaction as `approval.save()`.

### 5.3 RequestApprovedTrigger

**Fires when:** `Request.status` transitions to `APPROVED` (all serial approval steps done, ready for payment).

**Action:** Creates a "Process payment" `Task`. Assignee is determined by the request's `payment_type` (matches existing visibility rules in `apps/modules/requests/views.py`):

| `Request.payment_type` | Task assignee role |
|---|---|
| `cash` | `cashier` |
| `transfer`, `topup`, `card` | `accountant` |

- If multiple users hold the role in the tenant, the task is assigned to the first one (alphabetical by username) — directors/admins can reassign manually.
- `title` = "Process payment for request #{request.id}"
- `source_type` = `request_approved`
- `source_request` = the Request

**Hook point:** Inside `_recalculate_request_status()`, in the branch where `next_status == Request.STATUS_APPROVED`.

### 5.4 PaymentConfirmedTrigger

**Fires when:** A payment expense is created (`create_expense_for_request_payment()` in `requests/services.py`) and `Request.status` becomes `PAYED`.

**Action:**
- Closes the "Process payment" task (atomic)
- Creates a "Verify transaction" task. Same role mapping as above:
  - Cash expense → `cashier`
  - Bank/card expense → `accountant`
- For v1, the verifier defaults to the same person who processed the payment (the assignee of the "Process payment" task). Director/admin can reassign.

**Hook point:** Inside `dispatch_request_payed_event_handlers()` in `status_events.py`.

### 5.5 RequestRejectedTrigger

**Fires when:** `Request.status` transitions to `REJECTED`.

**Action:** Creates a "Notify and revise" task for the requester.
- `assignee` = `Request.requester`
- `title` = "Request #{request.id} rejected — review and decide next step"

**Hook point:** Inside `_recalculate_request_status()`, in the rejection branch.

### 5.6 EscalationTrigger

**Fires when:** A Celery beat job runs daily and finds approval steps pending for more than 3 days (hardcoded threshold for v1 — see Section 13 for rationale).

**Action:** Creates **one escalation task per director in the tenant** (each director gets their own copy). Whoever resolves it first marks it `done`; the others can also close theirs independently.

**Hook point:** New Celery beat job in `apps/modules/tasks/notifications/celery_tasks.py`.

---

## 6. Permissions (OCP)

### 6.1 Scoping classes (`querysets/`)

Each scope class implements:
```
class AbstractTaskScope:
    def filter_queryset(self, qs: QuerySet, user: User) -> QuerySet: ...
```

- `OwnTasksScope` — `qs.filter(assignee=user)` plus "last 3 done tasks" cap
- `TenantTasksScope` — `qs.filter(tenant=user.tenant)` (admin/director only)

A resolver function picks the scope based on the user's role — no `if`/`elif` chain inside the view.

### 6.2 "Last 3 done tasks" rule

When listing tasks, the `done` column is **capped to the most recent 3 per assignee** to keep the UI clean. Older done tasks are still in the database and accessible via:
- An "Archive" filter/tab in the UI
- The MCP `list_tenant_tasks` tool with `include_archived=true`

Implementation: a queryset method `with_capped_done(per_assignee=3)` that uses a window function (`row_number() over (partition by assignee, status order by completed_at desc)`) to filter.

### 6.3 Permission classes (`permissions.py`)

- `CanViewTask` — passes if user is assignee, or has role in (admin, director) and task is in user's tenant
- `CanCommentOnTask` — passes if user is assignee, or has role in (admin, director)
- `CanChangeStatus` — passes if user is assignee, or has role in (admin, director)

These are composable DRF permission classes following the pattern already used in `apps/tenants/permissions.py`.

---

## 7. API Endpoints

All under `/api/v1/tasks/`:

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/tasks/` | List tasks (scope auto-applied by user role) — supports `?status=`, `?assignee=`, `?source_type=` filters |
| POST | `/api/v1/tasks/` | Create a manual task |
| GET | `/api/v1/tasks/{id}/` | Retrieve a single task with comments |
| PATCH | `/api/v1/tasks/{id}/` | Update title/description (only by assignee or admin/director) |
| POST | `/api/v1/tasks/{id}/status/` | Change status — body: `{"status": "in_progress"}` |
| POST | `/api/v1/tasks/{id}/comments/` | Add a comment |
| GET | `/api/v1/tasks/dashboard/` | Aggregated counts for the current user: `{new: N, in_progress: N, done_recent: [...3 items]}` |

The dashboard endpoint also powers the Telegram morning digest.

---

## 8. Telegram Daily Digest (9:00 AM Tashkent / UTC+5)

### 8.1 Mechanism

A Celery beat job runs daily at 04:00 UTC (= 09:00 Asia/Tashkent). It:

1. Iterates over every active user in every tenant
2. Builds a per-user digest from `task_service.get_user_dashboard(user)`
3. Sends the digest via the existing `tg-gateway` integration (reuses Telegram bot tokens from `Tenant`)
4. Includes an inline button "Open Tasks" — uses the **same Telegram WebApp pattern** that approvals already use (see `apps/modules/telegram_approvals/formatter.py:303` `_resolve_comment_webapp_url`). A new `tasks_webapp_url` field is added to the tenant-level config; if set, the button opens the React webapp inside Telegram's webview (mini app). If not configured, the button is omitted.

### 8.2 Sample message format

```
☀ Good morning, {first_name}!

📋 NEW TASKS (3):
  • Approve request #4521 — Vendor: ACME Logistics
  • Approve request #4522 — Vendor: Beta Supplies
  • Process payment for request #4519

🔧 IN PROGRESS (1):
  • Verify transaction for request #4518

✅ RECENTLY COMPLETED (last 3):
  • Approved request #4517
  • Verified transaction #4516
  • Closed escalation #4515

[ Open Tasks ]   <-- button to webapp
```

### 8.3 OCP design

The digest is composed by a `TelegramDailyDigestChannel` class. Adding email digests later means creating an `EmailDailyDigestChannel` — no changes to the Celery job, which iterates over registered channels.

---

## 9. MCP Integration

A new tool file: `backend_v2/apps/mcp_server/tools/tasks.py`.

### 9.1 Exposed tools

| Tool | Purpose |
|---|---|
| `list_my_tasks` | Current user's tasks, filterable by status |
| `list_tenant_tasks` | Admin/director only — all tenant tasks |
| `get_task` | Full task detail including comments |
| `create_task` | Create a manual task (with assignee, title, description, due_date) |
| `update_task_status` | Move task between `new` → `in_progress` → `done` |
| `add_task_comment` | Post a comment (respects permissions) |
| `get_my_task_dashboard` | Same data as the morning digest — useful for ad-hoc Claude queries |

Each tool calls `task_service` directly (same service the REST API uses) — no logic duplication.

### 9.2 Authentication

Uses the existing MCP server auth (OAuth/PAT in `apps/mcp_server/auth.py`). The MCP context provides the user, and permission scoping is applied automatically via the same scope classes as the REST API.

---

## 10. Frontend (React + Ant Design)

### 10.1 New pages

```
frontend_v2/src/ui/tasks/
├── TasksPage.tsx              # main board view
├── TasksFilters.tsx           # filter bar (status, assignee for admins, source)
├── TaskCard.tsx               # one task tile
├── TaskDetailModal.tsx        # detail view with comments
├── TaskCreateModal.tsx        # manual task creation
└── TaskCommentList.tsx        # comment thread
```

API helpers in `frontend_v2/src/lib/tasksApi.ts` following the existing lib structure.

### 10.2 Layout

**Default view (board):** three columns using Ant Design's `Card` and `List` components:

```
┌──────────────┬───────────────────┬──────────────────┐
│   NEW (5)    │  IN PROGRESS (2)  │  DONE (last 3)   │
├──────────────┼───────────────────┼──────────────────┤
│ ┌──────────┐ │ ┌──────────────┐  │ ┌──────────────┐ │
│ │ Task #1  │ │ │ Task #6      │  │ │ Task #11 ✓   │ │
│ │ Approve  │ │ │ Process pay  │  │ │ done 5/24    │ │
│ └──────────┘ │ └──────────────┘  │ └──────────────┘ │
│ ┌──────────┐ │ ┌──────────────┐  │ ┌──────────────┐ │
│ │ Task #2  │ │ │ Task #7      │  │ │ Task #10 ✓   │ │
│ └──────────┘ │ └──────────────┘  │ └──────────────┘ │
│  ... 3 more  │                   │ ┌──────────────┐ │
│              │                   │ │ Task #9 ✓    │ │
│              │                   │ └──────────────┘ │
└──────────────┴───────────────────┴──────────────────┘
                                    [ View archive ]
```

Click a card → opens `TaskDetailModal` with full description, comments thread, status dropdown, and (for admin/director on another user's task) a comment input.

### 10.3 Director / admin view

When the logged-in user has role `admin` or `director`, the board adds an **assignee filter** at the top (multi-select dropdown of tenant users) and a "Show all" / "My tasks only" toggle. Default view is "All tenant tasks".

### 10.4 UX polish details

- Real-time updates: poll the dashboard endpoint every 30 seconds (WebSocket can come later if needed)
- Status change: drag-and-drop between columns (Ant Design has `@dnd-kit` patterns)
- Comments: clear visual distinction between assignee and admin/director comments (color tag)
- Visual cue when admin/director leaves a comment: small badge on the task card so the assignee notices ("New comment from director")
- Empty states: friendly messaging ("No new tasks — you're all caught up 🎉" — only place we use an emoji, in the UI)
- Mobile responsive: columns stack vertically on small screens

---

## 11. Backend Hook Points (Where Code Changes)

The trigger system means most logic lives in new files. The minimal edits to existing files:

| File | Edit |
|---|---|
| `apps/modules/requests/approval_workflow.py` | Add `TaskTriggerRegistry.dispatch("approval_step_activated", ...)` after `dispatch_pending_approvals` |
| `apps/modules/requests/approval_workflow.py` | Add `TaskTriggerRegistry.dispatch("approval_step_decided", ...)` inside `confirm_approval_by_id` |
| `apps/modules/requests/status_events.py` | Add dispatches for `request_approved`, `payment_confirmed`, `request_rejected` |
| `config/celery.py` | Register the daily digest beat schedule + escalation beat job |
| `config/urls.py` | Mount `apps/modules/tasks/urls.py` at `/api/v1/tasks/` |
| `apps/mcp_server/server.py` | Register the new `tasks` tool module |
| `frontend_v2/src/routes/App.tsx` | Add the `/tasks` route |
| `frontend_v2/src/ui/Sidebar.tsx` (or equivalent) | Add the "Tasks" menu item |

Everything else is **new files** — no business logic modifications to existing modules. This is the OCP principle in action.

---

## 12. Implementation Phases

### Phase 1 — Foundation (Backend core)
1. Create `apps/modules/tasks/` skeleton (models, migrations, admin)
2. Implement `task_service` and `comment_service`
3. Build the trigger registry and base classes
4. REST API endpoints + permissions
5. Wire the first trigger: `ApprovalStepActivatedTrigger` + `ApprovalStepDecidedTrigger`

### Phase 2 — All triggers + MCP
1. Implement remaining triggers (request_approved, payment_confirmed, request_rejected, escalation)
2. Add MCP tools file `apps/mcp_server/tools/tasks.py`

### Phase 3 — Frontend
1. Task board page with 3 columns
2. Task detail modal with comments
3. Manual task creation modal
4. Admin/director view (assignee filter, "Show all" toggle)
5. Sidebar menu integration

### Phase 4 — Notifications
1. Celery beat job for daily 9:00 AM Tashkent digest
2. Telegram message template + webapp button
3. Escalation Celery beat job

### Phase 5 — Polish
1. "Last 3 done tasks" cap + archive view
2. Drag-and-drop between status columns
3. "New comment from director/admin" badge on the assignee's task card
4. Mobile responsive layout

---

## 13. Resolved Decisions (Answers from review)

| # | Question | Decision |
|---|---|---|
| 1 | Payment task assignee | Derived from `Request.payment_type`: `cash` → cashier; `transfer`/`topup`/`card` → accountant (matches existing visibility rules in `apps/modules/requests/views.py:613-632`) |
| 2 | Verification task assignee | Same role mapping as #1 — defaults to the same person who processed the payment, reassignable by director/admin |
| 3 | Escalation threshold | **Hardcoded 3 days for v1**, exposed as a constant `ESCALATION_THRESHOLD_DAYS` in the trigger module. Per-tenant configurability can be added later as a `TenantConfig` field if needed (deferred to v2) |
| 4 | Escalation distribution | One escalation task per director in the tenant — each closes their own copy independently |
| 5 | Comments | Append-only in v1 (no edit/delete) |
| 6 | Telegram webapp | Reuse existing TG mini app pattern from `apps/modules/telegram_approvals/formatter.py` (`_resolve_comment_webapp_url`). A new `tasks_webapp_url` config field is read at digest-send time and used as the button URL |
| 7 | Deploy backfill | **New only** — no backfill. Pending approvals existing at deploy time will not receive tasks; only new approval events after deploy create tasks |

### Note on question 3 (escalation threshold)

For clarity: the original question was whether each tenant should be able to set their own threshold (e.g., Tenant A escalates after 2 days, Tenant B after 5 days) via the admin UI, or whether a single fixed value (3 days for everyone) is fine.

**Resolution:** Going with a single hardcoded constant for v1 to keep scope small. If different tenants need different policies later, we add a `TenantConfig.task_escalation_days` field — easy non-breaking change.

---

## 14. What This Plan Does NOT Include

To stay focused on the stated goal, the following are explicitly **out of scope** for v1:

- **Per-task deadlines / due dates** (removed by decision — no timer or deadline field on Task)
- **Overdue highlighting** (no due dates → nothing to mark as overdue)
- Recurring tasks (e.g., "monthly inventory check")
- Subtasks / task dependencies
- Task templates
- Calendar view / Gantt chart
- File attachments on tasks
- Email notifications (Telegram + in-app only)
- WebSocket real-time updates (polling is fine for v1)
- Multi-assignee tasks (one task = one person, by requirement)
- Edit/delete comments
- Task time tracking

These can all be added later — and because the design is OCP-compliant, each addition will be a new class or file, not a rewrite.

---

## 15. Summary

A **new Django module** (`apps/modules/tasks/`) provides task storage, auto-triggers, MCP access, REST API, and notifications — all built on the existing infrastructure (PostgreSQL, Celery, FastMCP, tg-gateway). The **OCP structure** means every new feature (new trigger, new notification channel, new permission scope) is a new file, not an edit to existing logic.

The **frontend** is a clean Kanban-style 3-column board with comments and admin/director scoping, using the same React + Ant Design patterns already in the codebase.

**Daily 9 AM Tashkent Telegram digests** reuse the existing tg-gateway to give every user a morning summary of their tasks with a button to open the webapp.

**Zero new infrastructure.** Zero external dependencies. Full data sovereignty. Atomic synchronization with approvals and payments.

---

*All decisions in Section 13 confirmed. Ready to start Phase 1.*
