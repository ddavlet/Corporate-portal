// n8n Code node (JavaScript)

const expensesRaw = $input.first().json;
const requestsRaw = $input.last().json;

const expensesArr = Array.isArray(expensesRaw) ? expensesRaw : (expensesRaw.expenses ?? []);
const requestsArr = Array.isArray(requestsRaw) ? requestsRaw : (requestsRaw.requests ?? []);

if (!Array.isArray(expensesArr) || !Array.isArray(requestsArr)) {
    throw new Error(
        `Expected arrays. Got expensesArr=${Array.isArray(expensesArr)} requestsArr=${Array.isArray(requestsArr)}`
    );
}

// ---- helpers ----
function parsePayedAtToUTCDate(payedAt) {
    if (payedAt === null || payedAt === undefined) return null;
    const s = String(payedAt).trim();
    if (!/^\d{8}$/.test(s)) return null;
    const y = Number(s.slice(0, 4));
    const m = Number(s.slice(4, 6));
    const d = Number(s.slice(6, 8));
    return new Date(Date.UTC(y, m - 1, d, 0, 0, 0, 0));
}

function expenseDateKey(expenseDateIso) {
    if (!expenseDateIso) return null;
    const dt = new Date(expenseDateIso);
    if (Number.isNaN(dt.getTime())) return null;
    return dt.toISOString().slice(0, 10); // UTC date key
}

// Also keep expense date as UTC-midnight Date for day-diff math (for MaybeMatch)
function expenseDateToUTCDate(expenseDateIso) {
    if (!expenseDateIso) return null;
    const dt = new Date(expenseDateIso);
    if (Number.isNaN(dt.getTime())) return null;
    const key = dt.toISOString().slice(0, 10); // YYYY-MM-DD
    return new Date(`${key}T00:00:00.000Z`);
}

function utcDateKey(dateObj) {
    return dateObj.toISOString().slice(0, 10);
}

function toNumber(val) {
    if (val === null || val === undefined) return null;
    if (typeof val === "number") return Number.isFinite(val) ? val : null;
    const n = Number(String(val).replace(/[^\d.-]/g, ""));
    return Number.isFinite(n) ? n : null;
}

function diffDaysUTC(a, b) {
    // a - b in days
    const ms = a.getTime() - b.getTime();
    return Math.round(ms / (24 * 60 * 60 * 1000));
}

// ---- normalize ----
expensesArr.forEach((e) => {
    e.__total_sum_num = toNumber(e.total_sum);
    e.__date_key = expenseDateKey(e.date);
    e.__date_utc = expenseDateToUTCDate(e.date); // for MaybeMatch
});

requestsArr.forEach((r) => {
    r.__amount_num = toNumber(r.amount);
    r.__payed_date = parsePayedAtToUTCDate(r.payed_at);
});

// ---- index expenses by amount only (no date constraint) ----
const expensesByAmount = new Map(); // amount -> [idx...]
expensesArr.forEach((e, idx) => {
    if (e.__total_sum_num === null) return;
    if (!expensesByAmount.has(e.__total_sum_num)) expensesByAmount.set(e.__total_sum_num, []);
    expensesByAmount.get(e.__total_sum_num).push(idx);
});

// Track used expenses (prevents reuse)
const usedExpenseIdx = new Set();
const matchedRequestIdx = new Set();

// outputs
const MatchedRequests = [];
const MatchedExpenses = [];
let UnmatchedRequests = [];
let UnmatchedExpenses = [];

// core matcher: amount only, no date. Match ONLY when exactly one candidate.
// Multiple candidates or zero → do NOT match; expenses not used; go to MaybeMatch.
function tryMatchRequest(req) {
    const amount = req.__amount_num;
    if (amount === null) return null;

    const candidates = expensesByAmount.get(amount) || [];
    const freeIndices = candidates.filter((i) => !usedExpenseIdx.has(i));
    if (freeIndices.length === 1) return freeIndices[0];
    return null;
}

// ---- single pass: match by amount only (exactly one candidate) ----
requestsArr.forEach((req, reqIdx) => {
    const matchedIdx = tryMatchRequest(req);
    if (matchedIdx === null) return;

    usedExpenseIdx.add(matchedIdx);
    matchedRequestIdx.add(reqIdx);

    const exp = expensesArr[matchedIdx];

    const reqOut = { ...req, expense_id: exp.id ?? null };
    const expOut = { ...exp, request_id: req.id ?? null };

    if (!reqOut.expense_id) throw new Error(`Matched expense missing 'id'. expense.pk=${exp.pk ?? "n/a"}`);
    if (!expOut.request_id) throw new Error(`Matched request missing 'id'. request.request_id=${req.request_id ?? "n/a"}`);

    delete reqOut.__amount_num;
    delete reqOut.__payed_date;
    delete expOut.__total_sum_num;
    delete expOut.__date_key;
    delete expOut.__date_utc;

    MatchedRequests.push(reqOut);
    MatchedExpenses.push(expOut);
});

// ---- MAYBE MATCH: same amount only (no date constraint) ----
// All unmatched request × unmatched expense pairs with same amount.
const MaybeMatch = [];

const unmatchedRequestObjs = requestsArr
    .map((r, idx) => ({ r, idx }))
    .filter(({ idx }) => !matchedRequestIdx.has(idx))
    .map(({ r }) => r);

const unmatchedExpenseObjs = expensesArr
    .map((e, idx) => ({ e, idx }))
    .filter(({ idx }) => !usedExpenseIdx.has(idx))
    .map(({ e }) => e);

const unmatchedExpensesByAmount = new Map(); // amount -> [expense...]
for (const e of unmatchedExpenseObjs) {
    if (e.__total_sum_num === null) continue;
    if (!unmatchedExpensesByAmount.has(e.__total_sum_num)) unmatchedExpensesByAmount.set(e.__total_sum_num, []);
    unmatchedExpensesByAmount.get(e.__total_sum_num).push(e);
}

for (const r of unmatchedRequestObjs) {
    const amount = r.__amount_num;
    if (amount === null) continue;

    const payedDate = r.__payed_date;
    const candidates = unmatchedExpensesByAmount.get(amount) || [];
    for (const e of candidates) {
        const dayDiff =
            payedDate && e.__date_utc ? diffDaysUTC(e.__date_utc, payedDate) : null; // expense - payed (for display/sort only)

        MaybeMatch.push({
            // IDs
            request_id: r.id ?? null,
            expense_id: e.id ?? null,

            // money & dates (for display and sort only)
            amount,
            payed_date: payedDate ? utcDateKey(payedDate) : null,
            expense_date: e.__date_utc ? utcDateKey(e.__date_utc) : null,
            day_diff: dayDiff,

            // ---- REQUEST CONTEXT ----
            request_title: r.title ?? null,
            request_purpose: r.payment_purpose ?? null,
            request_description: r.description ?? null,
            request_category: r.category ?? null,
            request_submitted_at: r.submitted_at ?? null,

            // ---- EXPENSE CONTEXT ----
            expense_comment: e.comment ?? null,
            expense_operation: e.operation ?? null,
            expense_counterparty: e.counterparty ?? null,
            expense_category: e.cathegory ?? null,
        });
    }
}

// Closest date first = best candidates at top (null day_diff last)
MaybeMatch.sort((a, b) => {
    const ad = a.day_diff == null ? Infinity : Math.abs(a.day_diff);
    const bd = b.day_diff == null ? Infinity : Math.abs(b.day_diff);
    return ad - bd;
});

// ---- Unmatched: only items that do NOT appear in MaybeMatch ----
const inMaybeMatchRequestIds = new Set(MaybeMatch.map((m) => m.request_id));
const inMaybeMatchExpenseIds = new Set(MaybeMatch.map((m) => m.expense_id));

UnmatchedRequests = unmatchedRequestObjs
    .filter((r) => !inMaybeMatchRequestIds.has(r.id ?? null))
    .map((r) => {
        const clean = { ...r };
        delete clean.__amount_num;
        delete clean.__payed_date;
        return clean;
    });

UnmatchedExpenses = unmatchedExpenseObjs
    .filter((e) => !inMaybeMatchExpenseIds.has(e.id ?? null))
    .map((e) => {
        const clean = { ...e };
        delete clean.__total_sum_num;
        delete clean.__date_key;
        delete clean.__date_utc;
        return clean;
    });

// ---- invariant ----
if (MatchedRequests.length !== MatchedExpenses.length) {
    throw new Error(
        `Invariant violated: matched requests (${MatchedRequests.length}) != matched expenses (${MatchedExpenses.length})`
    );
}

return [
    {
        json: {
            MatchedRequests,
            MatchedExpenses,
            UnmatchedRequests,
            UnmatchedExpenses,
            MaybeMatch,
            stats: {
                requests_in: requestsArr.length,
                expenses_in: expensesArr.length,
                matched_pairs: MatchedRequests.length,
                unmatched_requests: UnmatchedRequests.length,
                unmatched_expenses: UnmatchedExpenses.length,
                maybe_pairs: MaybeMatch.length,
            },
        },
    },
];
