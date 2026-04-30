"""
Integration test script for the Messaging Gateway.
Sends real HTTP requests to a running gateway instance.

Environment variables (required):
  BOT_TOKEN=<your_telegram_bot_token>
  RECIPIENT_ID=<your_telegram_chat_id>

Optional:
  GATEWAY_URL=http://localhost:8080   (default)
  TENANT_ID=test                      (default)

Run:
  $env:BOT_TOKEN="<token>"
  $env:RECIPIENT_ID="<chat_id>"
  python test_endpoints.py

  Add --no-cleanup to keep sent messages visible in Telegram:
  python test_endpoints.py --no-cleanup
"""
import os
import sys
import time
import httpx

GATEWAY_URL  = os.environ.get("GATEWAY_URL",   "http://localhost:8080")
BOT_TOKEN    = os.environ.get("BOT_TOKEN",      "")
RECIPIENT_ID = os.environ.get("RECIPIENT_ID",   os.environ.get("CHAT_ID", ""))  # CHAT_ID kept for compat
TENANT_ID    = os.environ.get("TENANT_ID",     "test")
NO_CLEANUP   = "--no-cleanup" in sys.argv

SEND    = f"{GATEWAY_URL}/v1/messaging/send"
RESULTS: list[tuple[bool, str]] = []

BASE = {
    "bot_token":    BOT_TOKEN,
    "tenant_id":    TENANT_ID,
    "recipient_id": RECIPIENT_ID,
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def req(label: str, payload: dict, expect: int = 200) -> dict:
    try:
        resp = httpx.post(SEND, json=payload, timeout=15)
        ok = resp.status_code == expect
        print(f"  {'✅' if ok else '❌'} {label}: [{resp.status_code}] {resp.text[:150]}")
        RESULTS.append((ok, label))
        return resp.json() if resp.status_code == 200 else {}
    except Exception as exc:
        print(f"  ❌ {label}: EXCEPTION {exc}")
        RESULTS.append((False, label))
        return {}


def section(title: str) -> None:
    print(f"\n── {title} {'─' * max(0, 50 - len(title))}")


# ── Security checks ───────────────────────────────────────────────────────────

def test_security() -> None:
    section("Security")
    # bot_token must not appear in any response
    resp = httpx.post(SEND, json={**BASE, "action": "send", "text": "security check"}, timeout=10)
    if resp.status_code == 200:
        token_leaked = BOT_TOKEN in resp.text
        ok = not token_leaked
        print(f"  {'✅' if ok else '❌'} bot_token not in response: {'PASS' if ok else 'LEAKED'}")
        RESULTS.append((ok, "security: bot_token not leaked"))


# ── Validation ────────────────────────────────────────────────────────────────

def test_validation() -> None:
    section("Validation")
    req("unknown action → 422",    {**BASE, "action": "fly_to_moon", "text": "test"},      expect=422)
    req("missing recipient_id → 422", {"action": "send", "bot_token": BOT_TOKEN, "text": "hi"}, expect=422)
    req("old action send_message → 422", {**BASE, "action": "send_message", "text": "hi"}, expect=422)
    req("edit without message_id → 400", {**BASE, "action": "edit", "text": "no mid"},     expect=400)
    req("delete without message_id → 400", {**BASE, "action": "delete"},                   expect=400)


def run() -> None:
    if not BOT_TOKEN or not RECIPIENT_ID:
        print("ERROR: set BOT_TOKEN and RECIPIENT_ID env vars")
        sys.exit(1)

    print(f"\n{'═' * 58}")
    print(f"  Messaging Gateway — Integration Tests")
    print(f"  {GATEWAY_URL}  tenant={TENANT_ID}")
    print(f"{'═' * 58}")

    # ── Health ────────────────────────────────────────────────────────────────
    section("Health")
    try:
        resp = httpx.get(f"{GATEWAY_URL}/health", timeout=5)
        ok = resp.status_code == 200
        print(f"  {'✅' if ok else '❌'} /health [{resp.status_code}] {resp.text}")
        RESULTS.append((ok, "health"))
    except Exception as exc:
        print(f"  ❌ /health unreachable: {exc}")
        RESULTS.append((False, "health"))

    test_security()
    test_validation()

    # ── send ──────────────────────────────────────────────────────────────────
    section("send")
    d = req("send plain text", {**BASE, "action": "send",
        "text": "👋 <b>Hello</b> from gateway test!"})
    plain_mid = d.get("message_id")
    if plain_mid:
        print(f"    → recipient_id={d.get('recipient_id')} message_id={plain_mid}")

    # ── send_interactive — dynamic buttons ────────────────────────────────────
    section("send_interactive — approve/reject")
    d = req("approve / reject buttons", {**BASE, "action": "send_interactive",
        "text": "<b>Approval Request</b>\nAmount: 500 000 UZS",
        "approval_id": "test-42",
        "buttons": [[
            {"label": "✅ Approve", "value": "v2_42:a"},
            {"label": "❌ Reject",  "value": "v2_42:r"},
        ]]})
    approve_mid = d.get("message_id")
    if approve_mid:
        print(f"    → message_id={approve_mid}")

    section("send_interactive — pay/cancel")
    d = req("pay / cancel buttons", {**BASE, "action": "send_interactive",
        "text": "<b>Payment Request</b>\nAmount: 200 000 UZS",
        "buttons": [[
            {"label": "💰 Pay",    "value": "v2_43:a"},
            {"label": "❌ Cancel", "value": "v2_43:r"},
        ]]})
    pay_mid = d.get("message_id")

    if NO_CLEANUP:
        print("\n  ⚠️  --no-cleanup: skipping edit and delete — messages stay in Telegram")
    else:
        # ── edit ──────────────────────────────────────────────────────────────
        if plain_mid:
            section("edit")
            time.sleep(0.3)
            req("edit text only", {**BASE, "action": "edit",
                "message_id": plain_mid,
                "text": "✏️ This message was <b>edited</b> by the gateway"})

        # ── edit_interactive — replace buttons ────────────────────────────────
        if approve_mid:
            section("edit_interactive — replace buttons")
            time.sleep(0.3)
            req("replace approve/reject → pay/cancel", {**BASE,
                "action": "edit_interactive",
                "message_id": approve_mid,
                "text": "✏️ Updated to payment flow",
                "buttons": [[
                    {"label": "💰 Pay",    "value": "v2_42:a"},
                    {"label": "❌ Cancel", "value": "v2_42:r"},
                ]]})

        # ── edit — remove buttons (empty buttons array) ───────────────────────
        if pay_mid:
            section("edit — remove buttons")
            time.sleep(0.3)
            req("clear buttons from pay message", {**BASE, "action": "edit",
                "message_id": pay_mid,
                "text": "✅ Paid — buttons removed",
                "buttons": []})

        # ── delete ────────────────────────────────────────────────────────────
        section("delete")
        time.sleep(0.3)
        for mid, label in [(approve_mid, "approval"), (pay_mid, "pay"), (plain_mid, "plain")]:
            if mid:
                req(f"delete {label} message", {**BASE, "action": "delete", "message_id": mid})

    # ── Summary ───────────────────────────────────────────────────────────────
    passed = sum(1 for ok, _ in RESULTS if ok)
    total  = len(RESULTS)
    print(f"\n{'═' * 58}")
    print(f"  Results: {passed}/{total} passed")
    if passed < total:
        for ok, label in RESULTS:
            if not ok:
                print(f"    ❌ FAILED: {label}")
    print(f"{'═' * 58}\n")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    run()
