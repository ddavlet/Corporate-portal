# Unmatched expenses & requests – analysis

## Matching rules (from code)

- **Pass 1:** expense date in `{payed_at, payed_at+1, payed_at+2, payed_at+3}` days, same amount.
- **Pass 2:** (unmatched only) expense date in `{payed_at-1, payed_at-2, payed_at-3}` days, same amount.
- **Rule:** Match only when there is **exactly one** free candidate. If 0 or 2+ candidates → do not match (goes to MaybeMatch by amount only).

---

## Why items end up unmatched (expected)

| Reason | Explanation |
|--------|-------------|
| **Multiple candidates** | More than one expense has same amount in the date window → we don’t match (ambiguous). |
| **Expense already used** | One expense, but two requests in window → first request (by array order) gets the expense, second stays unmatched. |
| **No expense in window** | No expense with same amount on any of the 7 days (payed_at ±3). |
| **No request in window** | Expense exists but no request with same amount and payed_at in that expense’s window. |

---

## Unmatched requests (14) – reasons

| ID | Amount | payed_at | Comment / purpose | Likely reason |
|----|--------|----------|------------------|----------------|
| 389 | 2 400 000 | 20260103 | Таргет | **Multiple candidates:** several expenses 2 400 000 (Таргет, ремонт) on different days in window. |
| 398 | 49 155 000 | 20260106 | Ком услуги | **Expense used:** one expense 49 155 000 on 2026-01-05 (pass2); likely matched to another request first. |
| 407 | 180 000 | 20260108 | Аренда перфоратора, клей, клипсы | **Expense used:** one expense 180 000 on 2026-01-06 (pass2); comment matches 1-000000028. Another request with 180 000 in window may have taken it first. |
| 410 | 40 000 | 20260108 | Доставка карт в клуб | **Should check:** one expense 40 000 “доставка карт” on 2026-01-07 (pass2). Same purpose. If still unmatched, either another request took that expense or there is a second 40 000 in window. |
| 418 | 2 400 000 | 20260110 | Таргет | **Multiple candidates:** many 2 400 000 expenses (Таргет / ремонт) in window. |
| 421 | 1 500 000 | 20260112 | Дверь в хаммам | **Expense used:** expense 1 500 000 on 2026-01-11 (1-000000045) likely matched to another request. |
| 425 | 70 000 | 20260113 | Герметик жидкий гвоздь | **Should check:** one expense 70 000 “герметик для установки дверей хамам” on 2026-01-11 (pass2). Same product. If still unmatched, another request may have taken it or there are 2 expenses 70 000 in window. |
| 426 | 26 000 | 20260113 | Доставка формы(Бар) | **Should match:** only one expense 26 000 “доставка майки бар” on 2026-01-11 (pass2). Same purpose. If 426 is unmatched, re-run with current mock and check that 1-000000053 is not matched to another request (there is only one request with 26 000). |
| 434 | 400 000 | 20260115 | Услуги инспектора по ЭКО | **Multiple candidates:** two expenses 400 000 in window (01-14 “инспектора по ЭКО”, 01-19 “2 урны” / “Урна 2 штуки”). Two requests (434, 440) and two expenses → ambiguous pairings. |
| 437 | 20 000 | 20260118 | Бахилы в клуб | **Multiple candidates:** unmatched expenses include 200 000 (not 20 000). No 20 000 in unmatched expenses; expense 20 000 may exist in mock and be matched or there are 2+ in window. |
| 439 | 25 000 | 20260119 | Доставка брелков | No 25 000 in unmatched expenses; likely matched or no expense in window. |
| 440 | 400 000 | 20260119 | Урна 2 штуки | **Multiple candidates:** same as 434 – two 400 000 expenses in window. |
| 563 | 20 000 | 20260214 | Дорожные | No expense 20 000 on 2026-02-14 ±3 in unmatched list. |
| 562 | 40 000 | 20260214 | Ершик в уборную | No expense 40 000 on 2026-02-14 ±3 in unmatched list (1-000000123 is 40 000 on 02-01, outside window). |

---

## Unmatched expenses (19) – reasons

- **Same amount, same/similar purpose, but multiple expenses** → we don’t match (e.g. 550 000 ×2, 200 000 ×2, 2 400 000, 400 000).
- **No request with same amount in window** (e.g. 36 000, 80 000, 121 050 000, 43 000, 19 000, 55 000×2, 400 000, 36 000, etc.).
- **One request, two expenses in window** → we don’t match (e.g. 200 000 “гарант массажист” on 02-02 and 02-03; 60 000 “доставка формы” on 02-02; 1 590 000 / 300 000 / 60 000 with no or one request in window).

---

## Pairs that look like they should match (verify with current mock)

1. **Request 426 (26 000, 01-13) ↔ expense 1-000000053 (26 000, 01-11)**  
   “Доставка формы(Бар)” / “доставка майки бар”. Only one 26 000 request and one 26 000 expense in mock; 01-11 is in pass2 for payed_at 01-13. **Expected:** they match. If 426 is still unmatched, re-run and check that 1-000000053 is not consumed by another request.

2. **Request 410 (40 000, 01-08) ↔ expense 1-000000033 (40 000, 01-07)**  
   “Доставка карт в клуб” / “доставка карт”. 01-07 is pass2. If 410 is unmatched, check for a second 40 000 expense in 01-05..01-11 or another request that took 1-000000033.

3. **Request 425 (70 000, 01-13) ↔ expense 1-000000054 (70 000, 01-11)**  
   “Герметик жидкий гвоздь” / “герметик для установки дверей хамам”. 01-11 is pass2. If 425 is unmatched, check for another 70 000 request/expense in window.

4. **Request 407 (180 000, 01-08) ↔ expense 1-000000028 (180 000, 01-06)**  
   Comments match. 01-06 is pass2. If 407 is unmatched, 1-000000028 was likely matched to another request (e.g. same amount, payed 01-06 or 01-07).

---

## Recommendation

1. **Re-run** the code with the current `mock.json` and inspect:
   - Whether 426 is matched to 1-000000053.
   - Whether 410, 425, 407 are matched or unmatched, and to which expense/request.
2. **Optional:** add a small debug log when `freeIndices.size > 1` (amount + payed_at + count) to see which requests are left unmatched due to multiple candidates.
3. **MaybeMatch:** all unmatched request/expense pairs with the **same amount** (no date limit) are in MaybeMatch; check there for 426/1-000000053 if amounts are exact.
