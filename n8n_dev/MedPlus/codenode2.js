const ZONE = 'Asia/Tashkent';

// --- helpers ---
function replaceText(value, from, to) {
    if (value === null || value === undefined) return value;
    return String(value).split(from).join(to);
}

function textBeforeDelimiter(value, delim = '-') {
    if (value === null || value === undefined) return null;
    const s = String(value);
    const idx = s.indexOf(delim);
    return idx === -1 ? s.trim() : s.slice(0, idx).trim();
}

function parsePrice(val) {
    if (val === null || val === undefined) return 0;
    const s = String(val).trim().replace(',', '.');
    const n = Number(s);
    return Number.isFinite(n) ? n : 0;
}

function parseDateTimeRU(val) {
    if (!val) return null;
    const s = String(val).replace(/\s+/g, ' ').trim(); // normalize spaces
    const dt = DateTime.fromFormat(s, 'dd.MM.yyyy HH:mm', { zone: ZONE });
    return dt.isValid ? dt : null;
}

// --- input ---
// NEW: items = [{json:{...record1}}, {json:{...record2}}, ...]
const records = $input.all()
    .map(i => i.json)
    .filter(v => v && typeof v === 'object');

// --- transform ---
let rows = records.map(v => {
    const doctors = v.user_name ?? null;
    const patients = v.fio ?? null;

    const amount = parsePrice(v.price);

    const dt = parseDateTimeRU(v.date);
    const revenue_date = dt ? dt.setZone(ZONE).toISO({ suppressMilliseconds: true, includeOffset: true }) : null;
    const revenue_time = dt ? dt.startOf('hour').toFormat('HH:mm:ss') : null;

    const payment_method = v.payment_method ?? null;
    const payment_type = payment_method === 'Наличными' ? 'Наличная оплата' : 'Безналичная оплата';

    let service_group = v.group_name ?? null;
    service_group = replaceText(service_group, 'Группа', 'Лаборатория');
    service_group = replaceText(service_group, 'Медикаменты', 'Операция');

    let service_title = v.title ?? null;
    service_title = replaceText(service_title, 'ЛФК-Лечебная физкультура стационарная', 'Травматолог-Консультация');
    service_title = replaceText(service_title, 'ЛФК-Лечебная физкультура амбулаторная', 'Травматолог-Консультация');
    service_title = replaceText(service_title, 'ЛФК-ЛФК', 'Травматолог-Консультация');

    let service_category = textBeforeDelimiter(service_title, '-');
    service_category = replaceText(service_category, 'Алгология', 'Нейрохирургические операции');
    service_category = replaceText(service_category, 'Колопроктология', 'Хирургические операции');
    service_category = replaceText(service_category, 'Группа', 'Лаборатория');
    service_category = replaceText(service_category, 'ЛФК', 'Травматолог');

    let year = null, month = null, quarter = null;
    if (dt) {
        year = dt.year;
        month = dt.month;
        quarter = Math.floor((dt.month - 1) / 3) + 1;
    }

    return {
        id: v.id !== undefined && v.id !== null ? Number(v.id) : null,
        client_id: v.client_id !== undefined && v.client_id !== null ? Number(v.client_id) : null,
        doctors,
        patients,
        amount,
        payment_method,
        payment_type,
        revenue_date,
        revenue_time,
        service_title,
        service_group,
        service_category,
        year,
        month,
        quarter,
    };
});

// optional sort (only makes sense if the batch contains multiple items)
rows.sort((a, b) => {
    const da = a.revenue_date ? DateTime.fromISO(a.revenue_date).toMillis() : 0;
    const db = b.revenue_date ? DateTime.fromISO(b.revenue_date).toMillis() : 0;
    return db - da;
});

// output as n8n items
return rows.map(r => ({ json: r }));
