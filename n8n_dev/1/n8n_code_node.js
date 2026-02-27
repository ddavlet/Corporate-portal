// n8n Code node (ONE node): Client efficiency report + RFM
// Input: flat rows, each row = one order line, but includes repeated order+client fields.
// Sample input shape: mock.json (array of such rows).
// Required fields per row:
// - client_id, order_id, total_sum, order_year, order_month, order_day
// - product_name, qty, total (line total)
// Optional client fields per row: client_name, company_name, phone, telegram_username, email, address
//
// Grades: D = one risk factor; E = two risk factors (worse than D); F = three or more (worst).
// No state across runs — E/F are from how many problems the client has in this run.
//
// Output: one item per client, sorted F → E → D → C → B → A, then RFM, etc.

const rows = $input.all().map(i => i.json);

function toNum(v) {
    if (v === null || v === undefined) return 0;
    if (typeof v === 'number') return Number.isFinite(v) ? v : 0;
    const s = String(v).replace(/\s/g, '').replace(',', '.');
    const n = Number(s);
    return Number.isFinite(n) ? n : 0;
}

function dayKeyFromDerived(o) {
    const y = Number(o.order_year);
    const m = Number(o.order_month);
    const d = Number(o.order_day);
    if (!Number.isFinite(y) || !Number.isFinite(m) || !Number.isFinite(d)) return null;
    return `${String(y).padStart(4, '0')}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
}

function tercileCuts(values) {
    const v = values.slice().filter(x => Number.isFinite(x)).sort((a, b) => a - b);
    if (!v.length) return { p33: 0, p66: 0 };
    return {
        p33: v[Math.floor((v.length - 1) * 0.33)],
        p66: v[Math.floor((v.length - 1) * 0.66)],
    };
}
function scoreHighGood(value, cuts) {
    if (value >= cuts.p66) return 3;
    if (value >= cuts.p33) return 2;
    return 1;
}
function scoreLowGood(value, cuts) {
    if (value <= cuts.p33) return 3;
    if (value <= cuts.p66) return 2;
    return 1;
}

function median(values) {
    const v = values.slice().filter(x => Number.isFinite(x)).sort((a, b) => a - b);
    if (!v.length) return null;
    const mid = Math.floor(v.length / 2);
    return v.length % 2 ? v[mid] : (v[mid - 1] + v[mid]) / 2;
}

const now = DateTime.now().toLocal().startOf('day');

// Threshold: current inactivity is "normal" if <= INACTIVITY_NORMAL_MULTIPLE * typical interval
const INACTIVITY_NORMAL_MULTIPLE = 1.5;
// Last 2 purchases below this fraction of average check → D
const LAST_TWO_BELOW_USUAL_RATIO = 0.8;

// --- Aggregate ---
const byClient = new Map();
// To avoid counting order totals multiple times (because each order has multiple lines)
const orderSeen = new Set(); // key = `${client_id}||${order_id}`

for (const r of rows) {
    const clientId = r.client_id ? String(r.client_id) : null;
    const orderId = r.order_id ? String(r.order_id) : null;
    if (!clientId || !orderId) continue;

    const dayKey = dayKeyFromDerived(r);
    if (!dayKey) continue;

    if (!byClient.has(clientId)) {
        byClient.set(clientId, {
            // client fields (filled from any row)
            client_id: clientId,
            client_name: r.client_name ?? null,
            company_name: r.company_name ?? null,
            phone: r.phone ?? null,
            telegram_username: r.telegram_username ?? null,
            email: r.email ?? null,
            address: r.address ?? null,

            // last contact (from CRM/contacts — fill from rows if present)
            last_contact_date: r.last_contact_date ?? r.contact_date ?? null,
            last_contact_comment: r.last_contact_comment ?? r.contact_comment ?? null,
            last_contact_manager: r.last_contact_manager ?? r.contact_manager ?? null,

            // order aggregates
            orders_count: 0,
            total_spent: 0,

            // last/prev purchase (by dayKey; tie-breaker by orderId string)
            last: null, // { day, order_id, total_sum }
            prev: null,

            // all order days (one per order) for frequency analysis
            orderDays: [],

            // product aggregates
            productAgg: new Map(), // product_name -> { qtySum, totalSum }
        });
    }

    const agg = byClient.get(clientId);

    // fill missing client fields if later rows have them
    if (agg.client_name == null && r.client_name != null) agg.client_name = r.client_name;
    if (agg.company_name == null && r.company_name != null) agg.company_name = r.company_name;
    if (agg.phone == null && r.phone != null) agg.phone = r.phone;
    if (agg.telegram_username == null && r.telegram_username != null) agg.telegram_username = r.telegram_username;
    if (agg.email == null && r.email != null) agg.email = r.email;
    if (agg.address == null && r.address != null) agg.address = r.address;
    // Last contact: take the one with the latest date (or first non-null if no dates)
    const rowContactDate = r.last_contact_date ?? r.contact_date ?? null;
    const rowContactComment = r.last_contact_comment ?? r.contact_comment ?? null;
    const rowContactManager = r.last_contact_manager ?? r.contact_manager ?? null;
    if (rowContactDate != null || rowContactComment != null || rowContactManager != null) {
        const rowDateStr = rowContactDate != null ? String(rowContactDate).trim() : '';
        const aggDateStr = agg.last_contact_date != null ? String(agg.last_contact_date).trim() : '';
        const useRow = aggDateStr === '' || (rowDateStr !== '' && rowDateStr > aggDateStr);
        if (useRow) {
            agg.last_contact_date = rowContactDate;
            agg.last_contact_comment = rowContactComment;
            agg.last_contact_manager = rowContactManager;
        }
    }

    // count order total once per order
    const orderKey = `${clientId}||${orderId}`;
    if (!orderSeen.has(orderKey)) {
        orderSeen.add(orderKey);

        const orderTotal = toNum(r.total_sum); // MUST use total_sum for order
        agg.orders_count += 1;
        agg.total_spent += orderTotal;

        const ord = { day: dayKey, order_id: orderId, total_sum: orderTotal };

        // update last/prev
        const betterThan = (a, b) => {
            // a later than b?
            if (!b) return true;
            if (a.day !== b.day) return a.day > b.day;
            // tie-breaker
            return String(a.order_id).localeCompare(String(b.order_id)) > 0;
        };

        if (agg.last == null || betterThan(ord, agg.last)) {
            agg.prev = agg.last;
            agg.last = ord;
        } else if (agg.prev == null || betterThan(ord, agg.prev)) {
            // don't let prev equal last
            if (agg.last?.order_id !== ord.order_id) agg.prev = ord;
        }

        agg.orderDays.push(dayKey);
    }

    // product stats per line (favorite products)
    const pname = r.product_name ? String(r.product_name) : null;
    if (pname) {
        const qty = toNum(r.qty);
        const lineTotal = toNum(r.total); // MUST use line total for product row
        if (!agg.productAgg.has(pname)) agg.productAgg.set(pname, { qtySum: 0, totalSum: 0 });
        const p = agg.productAgg.get(pname);
        p.qtySum += qty;
        p.totalSum += lineTotal;
    }
}

// --- Build report rows ---
const report = [];

for (const agg of byClient.values()) {
    const avgCheck = agg.orders_count ? agg.total_spent / agg.orders_count : 0;

    const lastDt = agg.last?.day ? DateTime.fromISO(agg.last.day).toLocal().startOf('day') : null;
    const prevDt = agg.prev?.day ? DateTime.fromISO(agg.prev.day).toLocal().startOf('day') : null;

    const daysInactive =
        lastDt && lastDt.isValid ? Math.floor(now.diff(lastDt, 'days').days) : null;

    // Typical order frequency: median days between consecutive orders
    const uniqueDays = [...new Set(agg.orderDays)].sort();
    const gaps = [];
    for (let i = 1; i < uniqueDays.length; i++) {
        const a = DateTime.fromISO(uniqueDays[i - 1]).toLocal().startOf('day');
        const b = DateTime.fromISO(uniqueDays[i]).toLocal().startOf('day');
        if (a.isValid && b.isValid) gaps.push(Math.floor(b.diff(a, 'days').days));
    }
    const medianDaysBetweenOrders = median(gaps);
    const avgDaysBetweenOrders = gaps.length ? gaps.reduce((s, g) => s + g, 0) / gaps.length : null;

    const inactivityVsUsual =
        daysInactive != null && medianDaysBetweenOrders != null && medianDaysBetweenOrders > 0
            ? Math.round((daysInactive / medianDaysBetweenOrders) * 100) / 100
            : null;

    // Orders in last 90 days (by order date)
    const cutoff90 = now.minus({ days: 90 });
    const ordersInLast90Days = uniqueDays.filter(d => {
        const dt = DateTime.fromISO(d).toLocal().startOf('day');
        return dt.isValid && dt >= cutoff90;
    }).length;

    // favorites
    let favQtyName = null, favQtyVal = -1;
    let favTotName = null, favTotVal = -1;

    for (const [name, p] of agg.productAgg.entries()) {
        if (p.qtySum > favQtyVal) { favQtyVal = p.qtySum; favQtyName = name; }
        if (p.totalSum > favTotVal) { favTotVal = p.totalSum; favTotName = name; }
    }

    report.push({
        "ID клиента": agg.client_id,
        "Название Юр. Лица": agg.client_name,
        "Бренд (Название заведения)": agg.company_name,
        "Телефон": agg.phone,
        "Telegram": agg.telegram_username,
        "Email": agg.email,
        "Адрес": agg.address,

        "Предыдущий контакт (дата)": (() => {
            if (agg.last_contact_date == null) return null;
            const dt = DateTime.fromISO(String(agg.last_contact_date)).toLocal();
            return dt.isValid ? dt.toFormat('dd.MM.yyyy') : String(agg.last_contact_date);
        })(),
        "Предыдущий контакт (комментарий)": agg.last_contact_comment,
        "Предыдущий контакт (менеджер)": agg.last_contact_manager,

        "Количество покупок": agg.orders_count,
        "Сумма всех покупок": Math.round(agg.total_spent * 100) / 100,
        "Средний чек": Math.round(avgCheck * 100) / 100,

        "Последняя покупка": lastDt && lastDt.isValid ? lastDt.toISODate() : null,
        "ID последней покупки": agg.last?.order_id ?? null,
        "Сумма последней покупки": Math.round((agg.last?.total_sum ?? 0) * 100) / 100,

        "Предыдущая покупка": prevDt && prevDt.isValid ? prevDt.toISODate() : null,
        "ID предыдущей покупки": agg.prev?.order_id ?? null,
        "Сумма предыдущей покупки": Math.round((agg.prev?.total_sum ?? 0) * 100) / 100,

        "Разница последняя-предыдущая": agg.prev ? Math.round((agg.last.total_sum - agg.prev.total_sum) * 100) / 100 : null,
        "Разница последняя-средняя": avgCheck ? Math.round((agg.last.total_sum - avgCheck) * 100) / 100 : null,
        "Средний чек последних 2 заказов": agg.last != null && agg.prev != null
            ? Math.round(((agg.last.total_sum + agg.prev.total_sum) / 2) * 100) / 100
            : null,

        "Дней неактивности": daysInactive,

        "Медианный интервал между заказами (дней)": medianDaysBetweenOrders != null ? Math.round(medianDaysBetweenOrders * 100) / 100 : null,
        "Неактивность / обычный интервал": inactivityVsUsual,
        "Заказов за последние 90 дней": ordersInLast90Days,

        "Любимый товар (по количеству)": favQtyName,
        "Любимый товар qty (сумма)": favQtyVal >= 0 ? Math.round(favQtyVal * 1000) / 1000 : null,

        "Любимый товар (по сумме)": favTotName,
        "Любимый товар total (сумма)": favTotVal >= 0 ? Math.round(favTotVal * 100) / 100 : null,
    });
}

// --- RFM for all clients in report ---
const recVals = report.map(r => r["Дней неактивности"]).filter(v => v != null);
const freqVals = report.map(r => Number(r["Количество покупок"]));
const monVals = report.map(r => Number(r["Сумма всех покупок"]));

const recCuts = tercileCuts(recVals.length ? recVals : [0]);
const freqCuts = tercileCuts(freqVals.length ? freqVals : [0]);
const monCuts = tercileCuts(monVals.length ? monVals : [0]);

for (const r of report) {
    const rec = r["Дней неактивности"] == null ? recCuts.p66 : Number(r["Дней неактивности"]);

    const R = scoreLowGood(rec, recCuts);
    const F = scoreHighGood(Number(r["Количество покупок"]), freqCuts);
    const M = scoreHighGood(Number(r["Сумма всех покупок"]), monCuts);

    r["R Давность"] = R;
    r["F Частота"] = F;
    r["M Деньги"] = M;
    r["RFM"] = `${R}${F}${M}`;

    if (R === 3 && F === 3 && M === 3) r["Сегмент"] = "Champions";
    else if (R === 3 && (F >= 2 || M >= 2)) r["Сегмент"] = "Loyal / Potential Loyalist";
    else if (R === 2 && (F >= 2 || M >= 2)) r["Сегмент"] = "Need Attention";
    else if (R === 1 && (F >= 2 || M >= 2)) r["Сегмент"] = "At Risk";
    else if (R === 1 && F === 1 && M === 1) r["Сегмент"] = "Lost";
    else r["Сегмент"] = "Others";

    // Grade A/B/C/D/E/F by number of risk factors in this run: 1 → D, 2 → E, 3+ → F.
    // Risk factors: Lost, At Risk, inactivity > 1.5× usual, no orders 90+ days, last 2 orders < 80% of avg check.
    const segment = r["Сегмент"];
    const inactivityOk = r["Неактивность / обычный интервал"] != null && r["Неактивность / обычный интервал"] <= INACTIVITY_NORMAL_MULTIPLE;
    const inactivityRatio = r["Неактивность / обычный интервал"];
    const ordersCount = Number(r["Количество покупок"]) || 0;
    const ordersInLast90 = r["Заказов за последние 90 дней"] != null ? Number(r["Заказов за последние 90 дней"]) : 0;
    const daysInactive = r["Дней неактивности"] != null ? Number(r["Дней неактивности"]) : null;
    const avgCheck = Number(r["Средний чек"]) || 0;
    const lastTwoAvg = r["Средний чек последних 2 заказов"] != null ? Number(r["Средний чек последних 2 заказов"]) : null;
    const lastTwoBelowUsual = avgCheck > 0 && lastTwoAvg != null && lastTwoAvg < avgCheck * LAST_TWO_BELOW_USUAL_RATIO;

    const dReasons = [];
    if (segment === "Lost") dReasons.push("Сегмент Lost (давно не покупал, мало заказов).");
    else if (segment === "At Risk") dReasons.push("Сегмент At Risk (давно не покупал при прошлой активности).");
    if (!inactivityOk && ordersCount >= 2 && inactivityRatio != null) {
        const ratio = Math.round(inactivityRatio * 100) / 100;
        dReasons.push(`Неактивность в ${ratio} раз выше обычного интервала между заказами.`);
    }
    if (ordersCount >= 2 && ordersInLast90 === 0 && daysInactive != null && daysInactive > 90)
        dReasons.push("Нет заказов более 90 дней при прежней активности.");
    if (lastTwoBelowUsual)
        dReasons.push("Сумма последних двух заказов ниже обычного.");

    let grade, why;
    if (dReasons.length > 0) {
        const baseWhy = dReasons.join(" ");
        if (dReasons.length === 1) {
            grade = "D";
            why = baseWhy;
        } else if (dReasons.length === 2) {
            grade = "E";
            why = baseWhy + " Два фактора риска. Связаться в приоритете.";
        } else {
            grade = "F";
            why = baseWhy + " Три и более факторов риска. Срочно связаться.";
        }
        r["Количество факторов риска"] = dReasons.length;
    } else {
        if (segment === "Need Attention") {
            grade = "C";
            why = "Сегмент Need Attention. Стоит мониторить.";
        } else if (segment === "Champions" || segment === "Loyal / Potential Loyalist") {
            grade = "A";
            why = "Активный и ценный клиент. Всё в норме.";
        } else if (inactivityRatio != null && inactivityRatio > 1) {
            grade = "C";
            why = "Неактивность чуть выше обычного. Стоит мониторить.";
        } else if (segment === "Others" && (R === 1 || R === 2)) {
            grade = "B";
            why = "Средняя вовлечённость. Без срочных действий.";
        } else {
            grade = "B";
            why = "В норме. Без срочных действий.";
        }
    }
    r["Оценка"] = grade;
    r["Почему оценка"] = why;
}

// --- Sort: F, E, D first (need to contact), then C, B, A; then RFM, Monetary, Frequency, Recency ---
const gradeOrder = { F: 0, E: 1, D: 2, C: 3, B: 4, A: 5 };
report.sort((a, b) => {
    const gA = gradeOrder[a["Оценка"]] ?? 6;
    const gB = gradeOrder[b["Оценка"]] ?? 6;
    if (gA !== gB) return gA - gB;

    const rfmA = Number(a["RFM"]);
    const rfmB = Number(b["RFM"]);
    if (rfmB !== rfmA) return rfmB - rfmA;

    const mA = Number(a["Сумма всех покупок"]);
    const mB = Number(b["Сумма всех покупок"]);
    if (mB !== mA) return mB - mA;

    const fA = Number(a["Количество покупок"]);
    const fB = Number(b["Количество покупок"]);
    if (fB !== fA) return fB - fA;

    const dA = a["Дней неактивности"] ?? 999999;
    const dB = b["Дней неактивности"] ?? 999999;
    return dA - dB;
});

return report.map(r => ({ json: r }));
