"""
Integration test script for the Telegram Dispatch Gateway.
Sends real HTTP requests to a running gateway and prints results.

Environment variables:
  GATEWAY_URL=http://localhost:8080   (default)
  BOT_TOKEN=<your_telegram_bot_token>
  CHAT_ID=<your_telegram_chat_id>
  TENANT_ID=test                      (default)

Run:
  $env:BOT_TOKEN="8411387505:AAE0BSIOft8st2vPxrkOU7FuIdgymG81nsg"
  $env:CHAT_ID="8306054387"
  python test_endpoints.py

  Add --no-cleanup to keep sent messages visible in Telegram:
  python test_endpoints.py --no-cleanup
"""
import os
import sys
import time
import httpx

GATEWAY_URL = os.environ.get("GATEWAY_URL",  "http://localhost:8080")
BOT_TOKEN   = os.environ.get("BOT_TOKEN",    "")
CHAT_ID     = int(os.environ.get("CHAT_ID",  "0"))
TENANT_ID   = os.environ.get("TENANT_ID",   "test")
NO_CLEANUP  = "--no-cleanup" in sys.argv

SEND = f"{GATEWAY_URL}/v1/telegram/send"
RESULTS: list[tuple[bool, str]] = []

BASE = {
    "bot_token": BOT_TOKEN,
    "tenant_id": TENANT_ID,
    "chat_id": CHAT_ID,
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


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_health() -> None:
    section("Health")
    try:
        resp = httpx.get(f"{GATEWAY_URL}/health", timeout=5)
        ok = resp.status_code == 200
        print(f"  {'✅' if ok else '❌'} /health [{resp.status_code}] {resp.text}")
        RESULTS.append((ok, "health"))
    except Exception as exc:
        print(f"  ❌ /health unreachable: {exc}")
        RESULTS.append((False, "health"))


def test_validation() -> None:
    section("Validation")
    req("unknown action → 422", {**BASE, "action": "fly_to_moon", "text_message": "test"}, expect=422)
    req("missing chat_id → 422", {"action": "send_message", "bot_token": BOT_TOKEN, "text_message": "hi"}, expect=422)
    req("delete_message_button removed → 422", {**BASE, "action": "delete_message_button", "message_id": 1}, expect=422)
    req("edit without message_id → 400", {**BASE, "action": "edit_message", "text_message": "no mid"}, expect=400)
    req("delete without message_id → 400", {**BASE, "action": "delete_message"}, expect=400)


def run() -> None:
    if not BOT_TOKEN or not CHAT_ID:
        print("ERROR: set BOT_TOKEN and CHAT_ID env vars")
        sys.exit(1)

    print(f"\n{'═' * 58}")
    print(f"  Telegram Gateway — Integration Tests")
    print(f"  {GATEWAY_URL}  tenant={TENANT_ID}")
    print(f"{'═' * 58}")

    test_health()
    test_validation()

    # ── send_message ──────────────────────────────────────────────────────────
    section("send_message")
    d = req("send plain text", {**BASE, "action": "send_message",
        "text_message": "👋 <b>Hello</b> from gateway test!"})
    plain_mid = d.get("message_id")
    if plain_mid:
        print(f"    → tenant={d.get('tenant')} chat_id={d.get('chat_id')} message_id={plain_mid}")

    # ── send_message_button (dynamic buttons) ─────────────────────────────────
    section("send_message_button — dynamic buttons")
    d = req("approve / reject", {**BASE, "action": "send_message_button",
        "text_message": "<b>Approval Request</b>\nAmount: 500 000 UZS",
        "approval_id": "test-42",
        "inline_keyboard": [[
            {"text": "✅ Approve", "callback_data": "v2_42:a"},
            {"text": "❌ Reject",  "callback_data": "v2_42:r"},
        ]]})
    approve_mid = d.get("message_id")

    d = req("pay / cancel", {**BASE, "action": "send_message_button",
        "text_message": "<b>Payment Request</b>\nAmount: 200 000 UZS",
        "inline_keyboard": [[
            {"text": "💰 Pay",    "callback_data": "v2_43:a"},
            {"text": "❌ Cancel", "callback_data": "v2_43:r"},
        ]]})
    pay_mid = d.get("message_id")

    if NO_CLEANUP:
        print("\n  ⚠️  --no-cleanup: skipping edit and delete — messages stay in Telegram")
    else:
        # ── edit_message ──────────────────────────────────────────────────────
        if plain_mid:
            section("edit_message")
            time.sleep(0.3)
            req("edit text only", {**BASE, "action": "edit_message",
                "message_id": plain_mid,
                "text_message": "✏️ This message was <b>edited</b> by the gateway"})

        # ── edit_message_button — replace buttons ─────────────────────────────
        if approve_mid:
            section("edit_message_button — replace buttons")
            time.sleep(0.3)
            req("replace approve/reject with pay/cancel", {**BASE,
                "action": "edit_message_button",
                "message_id": approve_mid,
                "text_message": "✏️ Updated to payment flow",
                "inline_keyboard": [[
                    {"text": "💰 Pay",    "callback_data": "v2_42:a"},
                    {"text": "❌ Cancel", "callback_data": "v2_42:r"},
                ]]})

        # ── edit_message — remove buttons by sending empty keyboard ───────────
        if pay_mid:
            section("edit_message — remove buttons (empty keyboard)")
            time.sleep(0.3)
            req("clear buttons from pay message", {**BASE, "action": "edit_message",
                "message_id": pay_mid,
                "text_message": "✅ Paid — buttons removed",
                "inline_keyboard": []})

        # ── delete_message ────────────────────────────────────────────────────
        section("delete_message")
        time.sleep(0.3)
        for mid, label in [(approve_mid, "approval msg"), (pay_mid, "pay msg"), (plain_mid, "plain msg")]:
            if mid:
                req(f"delete {label}", {**BASE, "action": "delete_message", "message_id": mid})

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
