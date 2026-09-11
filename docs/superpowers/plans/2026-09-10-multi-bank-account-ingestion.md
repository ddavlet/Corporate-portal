# Multi-Bank-Account Statement Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a tenant have several real bank accounts (`BankAccount`/`Wallet` pairs) instead of exactly one, and let n8n route a statement batch to the right account via `?our_account_no=&our_mfo=` query params on the existing `/bank/expenses/batch/` and `/bank/revenues/batch/` endpoints.

**Architecture:** Loosen `BankAccount`'s one-per-tenant constraint to one-per-`(tenant, account_no, mfo)` plus a new `is_default` flag; fix the one spot that assumed a single row (`get_or_create_bank_wallet`) to resolve the default account safely; resolve a specific account from query params inside the n8n import serializers only, leaving `resolve_wallet_for_bank`/`assign_wallet_for_bank_movement`/the batch views untouched.

**Tech Stack:** Django 5 / DRF, `backend_v2` (Python), Django TestCase / DRF APITestCase, PostgreSQL.

**Spec:** `docs/superpowers/specs/2026-09-10-multi-bank-account-ingestion-design.md`

## Global Constraints

- No local test execution (`pytest`, `python manage.py test`) — verification happens exclusively through GitHub Actions "Backend Tests" after `make push`. Every task below writes tests but does not attempt to run them locally.
- No local Django migrations (`python manage.py makemigrations`) — migrations are generated on the server via `make makemigrations` and downloaded locally as a normal repo file, which is then committed like any other file.
- OCP: prefer new functions/classes over editing working code; the only edits to already-shipped logic are the two explicitly-flagged bugfixes below (`BankAccount`'s constraint, `get_or_create_bank_wallet`'s lookup), each carrying its own test per project rules.
- Commits happen locally per task; `make push` (and the resulting CI check) happens once, in the final task, not after every commit.
- New dependencies: none.

---

### Task 1: `BankAccount` — allow multiple accounts per tenant with a default flag

**Files:**
- Modify: `backend_v2/apps/modules/wallets/models.py:30-45` (the `BankAccount` class)
- Create (via `make makemigrations`, not hand-written): `backend_v2/apps/modules/wallets/migrations/0006_bankaccount_is_default.py` (exact number may differ — use whatever the command generates)
- Test: `backend_v2/apps/modules/wallets/tests.py` (new `BankAccountConstraintTests` class)

**Interfaces:**
- Produces: `BankAccount.is_default` (`BooleanField`, `default=False`); constraints `wallets_bankaccount_unique_per_account` on `(tenant, account_no, mfo)` and `wallets_bankaccount_one_default_per_tenant` on `tenant` where `is_default=True`. Task 2 depends on both.

- [ ] **Step 1: Edit the model**

Replace the `BankAccount` class in `backend_v2/apps/modules/wallets/models.py`:

```python
class BankAccount(models.Model):
    """
    Tenant-level anchor for a bank Wallet. A tenant may have several BankAccount rows —
    one per real bank account — distinguished by (account_no, mfo). Exactly one row per
    tenant may be `is_default=True`; it's the fallback used when a caller does not name a
    specific account (see wallets.resolution.get_or_create_bank_wallet). Do not treat
    statement-line `account_no`/`mfo` on BankExpense/BankRevenue as this anchor — those
    describe the counterparty, not "our" account (see module docstring above).
    """

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="bank_accounts_wallets", db_index=False)
    label = models.CharField(max_length=255, default="Основной")
    account_no = models.CharField(max_length=34, blank=True, default="")
    mfo = models.CharField(max_length=10, blank=True, default="")
    is_default = models.BooleanField(default=False)

    class Meta:
        db_table = "wallets_bank_accounts"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "account_no", "mfo"], name="wallets_bankaccount_unique_per_account"
            ),
            models.UniqueConstraint(
                fields=["tenant"],
                condition=models.Q(is_default=True),
                name="wallets_bankaccount_one_default_per_tenant",
            ),
        ]
```

This drops the old `wallets_bankaccount_one_per_tenant` constraint (replaced by the two above) — that removal is the bugfix the spec's OCP exception covers.

- [ ] **Step 2: Generate the migration on the server**

Run: `make makemigrations`

This SSHes to the server, runs Django's `makemigrations` there (autodetects: `AddField(is_default)`, `RemoveConstraint(wallets_bankaccount_one_per_tenant)`, `AddConstraint(wallets_bankaccount_unique_per_account)`, `AddConstraint(wallets_bankaccount_one_default_per_tenant)`), and downloads the resulting file into `backend_v2/apps/modules/wallets/migrations/`. Confirm the new file appeared and its `operations` list matches the four changes above — if the autodetector produced something different (e.g. it renamed instead of dropping+adding), read the generated file and adjust the model only if it's clearly wrong; do not hand-edit the migration file itself.

- [ ] **Step 3: Write the tests**

Add to `backend_v2/apps/modules/wallets/tests.py` (new imports needed: `from django.db import IntegrityError, transaction` alongside the existing imports):

```python
class BankAccountConstraintTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", subdomain="bank-multi", is_active=True)

    def test_second_account_with_distinct_number_allowed(self):
        BankAccount.objects.create(tenant=self.tenant, label="Основной", account_no="", mfo="", is_default=True)
        second = BankAccount.objects.create(tenant=self.tenant, label="Валютный", account_no="20208000111111111111", mfo="00450")
        self.assertIsNotNone(second.pk)
        self.assertEqual(BankAccount.objects.filter(tenant=self.tenant).count(), 2)

    def test_duplicate_account_number_rejected(self):
        BankAccount.objects.create(tenant=self.tenant, account_no="2020800011", mfo="00450")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                BankAccount.objects.create(tenant=self.tenant, account_no="2020800011", mfo="00450")

    def test_two_default_accounts_rejected(self):
        BankAccount.objects.create(tenant=self.tenant, account_no="111", mfo="00450", is_default=True)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                BankAccount.objects.create(tenant=self.tenant, account_no="222", mfo="00450", is_default=True)

    def test_non_default_accounts_can_share_blank_or_differ_freely(self):
        # Two tenants can each have their own blank-account_no row without colliding
        # (the unique constraint is per-tenant, not global).
        other_tenant = Tenant.objects.create(name="Beta", subdomain="bank-multi-2", is_active=True)
        BankAccount.objects.create(tenant=self.tenant, account_no="", mfo="")
        other = BankAccount.objects.create(tenant=other_tenant, account_no="", mfo="")
        self.assertIsNotNone(other.pk)
```

Add `BankAccount` to the existing import line near the top of `wallets/tests.py` — it currently imports only `CashRegister, Wallet` from `apps.modules.wallets.models` in some places and `BankAccount` elsewhere in the file; check the actual top-of-file imports and add `BankAccount` to `from apps.modules.wallets.models import ...` if not already present, alongside `Tenant` from `apps.tenants.models` (already imported).

- [ ] **Step 4: Commit**

```bash
git add backend_v2/apps/modules/wallets/models.py backend_v2/apps/modules/wallets/migrations/ backend_v2/apps/modules/wallets/tests.py
git commit -m "feat(wallets): allow multiple bank accounts per tenant"
```

---

### Task 2: Resolution helpers — safe default fallback + per-account resolution

**Files:**
- Modify: `backend_v2/apps/modules/wallets/resolution.py:67-81` (`get_or_create_bank_wallet`)
- Test: `backend_v2/apps/modules/wallets/tests.py` (new `BankWalletResolutionTests` class)

**Interfaces:**
- Consumes: `BankAccount.is_default` (Task 1).
- Produces: `get_or_create_bank_wallet(*, tenant) -> Wallet` (existing signature, fixed body); new `get_or_create_bank_wallet_for_account(*, tenant, account_no, mfo="") -> Wallet`. Task 3 calls `get_or_create_bank_wallet_for_account`.

- [ ] **Step 1: Fix `get_or_create_bank_wallet` and add `get_or_create_bank_wallet_for_account`**

In `backend_v2/apps/modules/wallets/resolution.py`, replace the current `get_or_create_bank_wallet` function:

```python
def get_or_create_bank_wallet(*, tenant: Tenant) -> Wallet:
    ba = BankAccount.objects.filter(tenant=tenant, is_default=True).first()
    if ba is None:
        ba, created = BankAccount.objects.get_or_create(
            tenant=tenant,
            account_no="",
            mfo="",
            defaults={"label": "Основной", "is_default": True},
        )
        if not created and not ba.is_default:
            ba.is_default = True
            ba.save(update_fields=["is_default"])
    w, _ = Wallet.objects.get_or_create(
        bank_account=ba,
        defaults={
            "tenant": tenant,
            "wallet_type": Wallet.Type.BANK,
            "currency": "UZS",
            "opening_balance": 0,
        },
    )
    return w


def get_or_create_bank_wallet_for_account(*, tenant: Tenant, account_no: str, mfo: str = "") -> Wallet:
    account_no = (account_no or "").strip()
    mfo = (mfo or "").strip()
    ba, _ = BankAccount.objects.get_or_create(
        tenant=tenant,
        account_no=account_no,
        mfo=mfo,
        defaults={"label": account_no},
    )
    w, _ = Wallet.objects.get_or_create(
        bank_account=ba,
        defaults={
            "tenant": tenant,
            "wallet_type": Wallet.Type.BANK,
            "currency": "UZS",
            "opening_balance": 0,
        },
    )
    return w
```

Do not touch `resolve_wallet_for_bank`, `resolve_wallet_for_cash`, `resolve_wallet_for_corporate`, or `get_or_create_cash_wallet`/`get_or_create_corporate_wallet` in this file — they are unaffected.

- [ ] **Step 2: Write the tests**

Add to `backend_v2/apps/modules/wallets/tests.py` (reuses the `get_or_create_bank_wallet`, `get_or_create_cash_wallet`, `get_or_create_corporate_wallet` import already at the top; add `get_or_create_bank_wallet_for_account` to that same `from apps.modules.wallets.resolution import (...)` line):

```python
class BankWalletResolutionTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", subdomain="bank-resolve", is_active=True)

    def test_default_wallet_created_once_for_fresh_tenant(self):
        w1 = get_or_create_bank_wallet(tenant=self.tenant)
        w2 = get_or_create_bank_wallet(tenant=self.tenant)
        self.assertEqual(w1.id, w2.id)
        self.assertEqual(BankAccount.objects.filter(tenant=self.tenant).count(), 1)
        self.assertTrue(BankAccount.objects.get(tenant=self.tenant).is_default)

    def test_legacy_blank_account_is_promoted_to_default_lazily(self):
        # Simulates a tenant that already had the old single BankAccount row before
        # this migration — is_default defaults to False at the schema level.
        legacy = BankAccount.objects.create(tenant=self.tenant, label="Основной", account_no="", mfo="")
        self.assertFalse(legacy.is_default)
        w = get_or_create_bank_wallet(tenant=self.tenant)
        legacy.refresh_from_db()
        self.assertTrue(legacy.is_default)
        self.assertEqual(Wallet.objects.get(bank_account=legacy).id, w.id)

    def test_named_account_created_and_reused(self):
        w1 = get_or_create_bank_wallet_for_account(tenant=self.tenant, account_no="20208000111111111111", mfo="00450")
        w2 = get_or_create_bank_wallet_for_account(tenant=self.tenant, account_no="20208000111111111111", mfo="00450")
        self.assertEqual(w1.id, w2.id)
        self.assertEqual(BankAccount.objects.filter(tenant=self.tenant).count(), 1)

    def test_named_account_does_not_collide_with_default(self):
        default_wallet = get_or_create_bank_wallet(tenant=self.tenant)
        named_wallet = get_or_create_bank_wallet_for_account(
            tenant=self.tenant, account_no="20208000111111111111", mfo="00450"
        )
        self.assertNotEqual(default_wallet.id, named_wallet.id)
        self.assertEqual(BankAccount.objects.filter(tenant=self.tenant).count(), 2)

    def test_default_resolution_does_not_crash_with_multiple_accounts(self):
        get_or_create_bank_wallet_for_account(tenant=self.tenant, account_no="111", mfo="00450")
        get_or_create_bank_wallet_for_account(tenant=self.tenant, account_no="222", mfo="00450")
        # Neither of the above is is_default=True, so the fallback must self-heal
        # exactly one of the tenant's rows into the default instead of raising
        # MultipleObjectsReturned.
        w = get_or_create_bank_wallet(tenant=self.tenant)
        self.assertIsNotNone(w.id)
        self.assertEqual(BankAccount.objects.filter(tenant=self.tenant, is_default=True).count(), 1)
```

- [ ] **Step 3: Commit**

```bash
git add backend_v2/apps/modules/wallets/resolution.py backend_v2/apps/modules/wallets/tests.py
git commit -m "feat(wallets): resolve default bank account safely, add per-account lookup"
```

---

### Task 3: n8n ingestion — resolve wallet from `our_account_no`/`our_mfo` query params

**Files:**
- Modify: `backend_v2/apps/modules/n8n_integration/serializers.py:214-266` (`N8nBankExpenseImportSerializer`, `N8nBankRevenueImportSerializer`), plus a new module-level helper in the same file
- Test: `backend_v2/apps/modules/n8n_integration/tests.py` (new test methods in `N8nIntegrationAuthTests`)

**Interfaces:**
- Consumes: `get_or_create_bank_wallet_for_account(*, tenant, account_no, mfo="") -> Wallet` (Task 2).
- Produces: nothing new consumed by later tasks — this is the last functional task.

- [ ] **Step 1: Add the import and the shared helper**

In `backend_v2/apps/modules/n8n_integration/serializers.py`, add to the imports (near the existing `from apps.modules.wallets.models import CashRegister` line):

```python
from apps.modules.wallets.resolution import get_or_create_bank_wallet_for_account
```

Add this module-level helper right above `class N8nBankExpenseImportSerializer(BankExpenseSerializer):`:

```python
def _inject_statement_wallet_from_query(serializer, attrs: dict) -> None:
    """
    A bank-statement import (single or batch) may pin the target wallet to a specific
    tenant bank account via `?our_account_no=...&our_mfo=...` on the request URL. Resolved
    once per HTTP call but applied per item, because _N8nBatchBaseView forwards the batch
    request's GET to every item's synthetic per-item request. An explicit `wallet_id`
    already present on the item (attrs["wallet"] set) always wins and is left untouched.
    """
    if attrs.get("wallet") is not None:
        return
    request_obj = serializer.context.get("request")
    query = getattr(request_obj, "GET", None) or {}
    account_no = str(query.get("our_account_no") or "").strip()
    if not account_no:
        return
    tenant = getattr(request_obj, "tenant", None)
    if tenant is None:
        return
    mfo = str(query.get("our_mfo") or "").strip()
    attrs["wallet"] = get_or_create_bank_wallet_for_account(tenant=tenant, account_no=account_no, mfo=mfo)
```

- [ ] **Step 2: Wire it into both import serializers**

In `N8nBankExpenseImportSerializer.validate()` (existing method), add the call right before the final `return super().validate(attrs)`:

```python
    def validate(self, attrs):
        tenant = getattr(self.context.get("request"), "tenant", None)
        self.context["allow_missing_vendor"] = True
        raw_account_no = attrs.get("account_no")
        account_no = str(raw_account_no or "").strip()
        vendor_name = str(attrs.pop("vendor_name", "") or "").strip()
        account_name = str(attrs.pop("account_name", "") or "").strip()
        counterparty = str(attrs.pop("counterparty", "") or "").strip()
        lookup_name = vendor_name or account_name or counterparty

        if attrs.get("vendor") is None and tenant and lookup_name and not account_no:
            matches = list(
                Vendor.objects.filter(
                    tenant=tenant,
                    kind=Vendor.KIND_TRANSFER,
                    name=lookup_name,
                )
                .order_by("id")[:2]
            )
            if not matches:
                raise serializers.ValidationError(
                    {"vendor_name": f"Transfer vendor with name '{lookup_name}' not found in current tenant."}
                )
            if len(matches) > 1:
                raise serializers.ValidationError(
                    {"vendor_name": f"Multiple transfer vendors found with name '{lookup_name}'."}
                )
            attrs["vendor"] = matches[0]
        _inject_statement_wallet_from_query(self, attrs)
        return super().validate(attrs)
```

(Only the added `_inject_statement_wallet_from_query(self, attrs)` line before `return super().validate(attrs)` is new — the rest of the method is unchanged, shown here for exact placement.)

`N8nBankRevenueImportSerializer` currently has no `validate()` override — add one:

```python
class N8nBankRevenueImportSerializer(BankRevenueSerializer):
    id = serializers.IntegerField(required=False, allow_null=True)

    def validate(self, attrs):
        _inject_statement_wallet_from_query(self, attrs)
        return super().validate(attrs)

    class Meta(BankRevenueSerializer.Meta):
        read_only_fields = ["created_at", "created_by"]
```

- [ ] **Step 3: Write the tests**

Add to `backend_v2/apps/modules/n8n_integration/tests.py`, inside `class N8nIntegrationAuthTests` (near the other `test_bank_expense_*`/`test_bank_revenue_*` methods, e.g. right after `test_bank_expense_batch_upserts_by_external_id`):

```python
    def test_bank_expense_our_account_no_creates_named_wallet(self):
        url = f"{self.n8n_prefix}/bank/expenses/?our_account_no=20208000222222222222&our_mfo=00450"
        body = {
            "external_id": "BANK-ACCT-1",
            "row_no": 1,
            "doc_date": "2026-09-01",
            "process_date": "2026-09-01",
            "doc_no": "BEXP-ACCT-1",
            "debit_turnover": "100.00",
            "payment_purpose": "Оплата",
        }
        res = self.client.post(url, body, format="json", **self._headers(self.admin))
        self.assertEqual(res.status_code, 201, res.content)
        row = BankExpense.objects.get(tenant=self.tenant, external_id="BANK-ACCT-1")
        ba = BankAccount.objects.get(tenant=self.tenant, account_no="20208000222222222222", mfo="00450")
        self.assertEqual(row.wallet.bank_account_id, ba.id)
        self.assertFalse(ba.is_default)

    def test_bank_expense_batch_applies_our_account_no_to_every_item(self):
        url = f"{self.n8n_prefix}/bank/expenses/batch/?our_account_no=20208000333333333333"
        items = [
            {
                "external_id": "BANK-ACCT-BATCH-1",
                "row_no": 1,
                "doc_date": "2026-09-01",
                "process_date": "2026-09-01",
                "doc_no": "BEXP-ACCT-BATCH-1",
                "debit_turnover": "10.00",
                "payment_purpose": "Оплата 1",
            },
            {
                "external_id": "BANK-ACCT-BATCH-2",
                "row_no": 2,
                "doc_date": "2026-09-01",
                "process_date": "2026-09-01",
                "doc_no": "BEXP-ACCT-BATCH-2",
                "debit_turnover": "20.00",
                "payment_purpose": "Оплата 2",
            },
        ]
        res = self.client.post(url, items, format="json", **self._headers(self.admin))
        self.assertEqual(res.status_code, 200, res.content)
        ba = BankAccount.objects.get(tenant=self.tenant, account_no="20208000333333333333")
        rows = BankExpense.objects.filter(
            tenant=self.tenant, external_id__in=["BANK-ACCT-BATCH-1", "BANK-ACCT-BATCH-2"]
        )
        self.assertEqual(rows.count(), 2)
        for row in rows:
            self.assertEqual(row.wallet.bank_account_id, ba.id)

    def test_bank_expense_explicit_wallet_id_overrides_our_account_no(self):
        other_wallet = get_or_create_bank_wallet(tenant=self.tenant)
        url = f"{self.n8n_prefix}/bank/expenses/?our_account_no=20208000444444444444"
        body = {
            "external_id": "BANK-ACCT-OVERRIDE-1",
            "row_no": 1,
            "doc_date": "2026-09-01",
            "process_date": "2026-09-01",
            "doc_no": "BEXP-ACCT-OVERRIDE-1",
            "debit_turnover": "5.00",
            "payment_purpose": "Оплата",
            "wallet_id": other_wallet.id,
        }
        res = self.client.post(url, body, format="json", **self._headers(self.admin))
        self.assertEqual(res.status_code, 201, res.content)
        row = BankExpense.objects.get(tenant=self.tenant, external_id="BANK-ACCT-OVERRIDE-1")
        self.assertEqual(row.wallet_id, other_wallet.id)
        self.assertFalse(BankAccount.objects.filter(tenant=self.tenant, account_no="20208000444444444444").exists())

    def test_bank_expense_without_our_account_no_keeps_default_wallet_behavior(self):
        url = f"{self.n8n_prefix}/bank/expenses/"
        body = {
            "external_id": "BANK-ACCT-DEFAULT-1",
            "row_no": 1,
            "doc_date": "2026-09-01",
            "process_date": "2026-09-01",
            "doc_no": "BEXP-ACCT-DEFAULT-1",
            "debit_turnover": "7.00",
            "payment_purpose": "Оплата",
        }
        res = self.client.post(url, body, format="json", **self._headers(self.admin))
        self.assertEqual(res.status_code, 201, res.content)
        row = BankExpense.objects.get(tenant=self.tenant, external_id="BANK-ACCT-DEFAULT-1")
        self.assertTrue(row.wallet.bank_account.is_default)

    def test_bank_revenue_our_account_no_creates_named_wallet(self):
        url = f"{self.n8n_prefix}/bank/revenues/?our_account_no=20208000555555555555&our_mfo=00450"
        body = {
            "external_id": "BREV-ACCT-1",
            "row_no": 1,
            "doc_date": "2026-09-01",
            "process_date": "2026-09-01",
            "doc_no": "BREV-ACCT-1",
            "account_name": "Client",
            "inn": "123",
            "account_no": "202080009999",
            "mfo": "01001",
            "kredit_turnover": "50.00",
            "payment_purpose": "Оплата",
        }
        res = self.client.post(url, body, format="json", **self._headers(self.admin))
        self.assertEqual(res.status_code, 201, res.content)
        row = BankRevenue.objects.get(tenant=self.tenant, external_id="BREV-ACCT-1")
        ba = BankAccount.objects.get(tenant=self.tenant, account_no="20208000555555555555", mfo="00450")
        self.assertEqual(row.wallet.bank_account_id, ba.id)
```

These reuse `self.tenant`, `self.admin`, `self.n8n_prefix`, `self._headers` from `N8nIntegrationAuthTests.setUp` (already defined at the top of the class, read in a prior step). Add `BankAccount` to the existing `from apps.modules.wallets.models import CashRegister, Wallet` import line at the top of `n8n_integration/tests.py` (becomes `from apps.modules.wallets.models import BankAccount, CashRegister, Wallet`) — `get_or_create_bank_wallet` is already imported there.

- [ ] **Step 4: Commit**

```bash
git add backend_v2/apps/modules/n8n_integration/serializers.py backend_v2/apps/modules/n8n_integration/tests.py
git commit -m "feat(n8n): resolve bank statement wallet from our_account_no/our_mfo query params"
```

---

### Task 4: Regression coverage — reconciliation and manual bank-account API stay correct

**Files:**
- Test: `backend_v2/apps/modules/requests/tests_bank_expense_reconciliation.py` (new test method)
- Test: `backend_v2/apps/modules/wallets/tests.py` (new test method in `WalletsApiTests`)

**Interfaces:**
- Consumes: `get_or_create_bank_wallet_for_account` (Task 2); the `/api/wallets/bank-accounts/` endpoint (unmodified, `BankAccountViewSet`/`BankAccountSerializer` in `wallets/views.py`/`wallets/serializers.py`).

- [ ] **Step 1: Add a multi-wallet regression test to the reconciliation suite**

Add to `backend_v2/apps/modules/requests/tests_bank_expense_reconciliation.py`, inside `class BankExpenseReconciliationTests` (it already imports `BankAccount, Wallet` from `apps.modules.wallets.models` — reuse that):

```python
    def test_matching_ignores_which_bank_wallet_the_expense_sits_on(self):
        second_account = BankAccount.objects.create(tenant=self.tenant, label="Второй", account_no="999", mfo="00450")
        second_wallet = Wallet.objects.create(
            tenant=self.tenant, wallet_type=Wallet.Type.BANK, currency="UZS", bank_account=second_account,
        )
        vendor = self._make_vendor()
        expense = BankExpense.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            row_no=1,
            doc_date=date(2026, 8, 10),
            process_date=date(2026, 8, 10),
            expense_year=2026,
            expense_month=8,
            expense_day=10,
            doc_no="",
            debit_turnover=Decimal("300"),
            payment_purpose="x",
            vendor=vendor,
            wallet=second_wallet,
        )
        request_obj = self._make_request(vendor=vendor, amount="300", payed_date=date(2026, 8, 10))

        reconcile_bank_expenses_by_vendor_amount_date(tenant=self.tenant)

        request_obj.refresh_from_db()
        self.assertEqual(request_obj.expense_ref_id, expense.pk)
        self.assertEqual(request_obj.expense_ref_target, Request.EXPENSE_REF_TARGET_BANK)
```

Place it near the other matching-behavior tests in the same class (read the file first to find a sensible spot next to similar `test_*` methods already covering the vendor+amount+date match).

- [ ] **Step 2: Add a regression test confirming the manual API now allows a second, distinct account**

Add to `backend_v2/apps/modules/wallets/tests.py`, inside `class WalletsApiTests` (right after the existing `test_bank_account_second_create_rejected`):

```python
    def test_bank_account_second_create_with_distinct_number_allowed(self):
        res = self.client.post(
            "/api/wallets/bank-accounts/",
            {"label": "Второй счёт", "account_no": "20208000777777777777", "mfo": "00450"},
            format="json",
            **self._headers(self.admin),
        )
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(BankAccount.objects.filter(tenant=self.tenant).count(), 2)
```

This complements the existing `test_bank_account_second_create_rejected` (which posts blank `account_no`/`mfo` and still correctly gets 400 under the new constraint, since both rows would collide on `("", "")`) — confirming the loosened constraint only permits *distinct* accounts, not unlimited duplicates.

- [ ] **Step 3: Commit**

```bash
git add backend_v2/apps/modules/requests/tests_bank_expense_reconciliation.py backend_v2/apps/modules/wallets/tests.py
git commit -m "test: confirm reconciliation and bank-account API handle multiple accounts"
```

---

### Task 5: Push and verify CI

**Files:** none (procedural).

- [ ] **Step 1: Push the branch**

Run: `make push`

Per project rules this checks everything is committed and pushes `dev/multi-bank-account-ingestion` to GitHub.

- [ ] **Step 2: Wait for and confirm GitHub Actions**

Check the "Backend Tests" workflow run for this branch/PR (e.g. `gh run list --branch dev/multi-bank-account-ingestion` / `gh pr checks`) and confirm it passes. If it fails, read the failure output, fix the root cause in the relevant task's files, commit a follow-up fix, and push again — do not skip or disable the failing test.

- [ ] **Step 3: Open the PR into `main`**

Per `CLAUDE.md`, direct pushes/commits to `main` are forbidden — open a Pull Request from `dev/multi-bank-account-ingestion` and reference `docs/superpowers/specs/2026-09-10-multi-bank-account-ingestion-design.md` in the description.
