// n8n Code node: organize months_breakdown data for Google Sheets
// Input: items with nested months_breakdown (or single item containing array)
// Output: one item per row with flat columns for Sheets

const items = $input.all();
const rows = [];

for (const item of items) {
  const data = item.json;

  // Support: 1) array of breakdowns, 2) single object, 3) wrapper with array inside
  let breakdowns = Array.isArray(data)
    ? data
    : data.months_breakdown != null && !Array.isArray(data.months_breakdown)
      ? [data]
      : data.months_breakdown ?? (data.data || data.rows || [data]);

  if (!Array.isArray(breakdowns)) breakdowns = [breakdowns];

  for (const row of breakdowns) {
    const mb = row.months_breakdown || row;
    const weightedDaysSum = row.weighted_days_sum ?? mb.weighted_days_sum ?? '';

    rows.push({
      json: {
        'Месяц': mb.month ?? '',
        'Месяц (проекция)': mb.month_projection ?? '',
        'Дней в периоде': mb.days_in_window ?? '',
        'Коэффициент': mb.coeficient ?? '',
        'Взвешенные дни': mb.weighted_days ?? '',
        'Сумма взвешенных дней': weightedDaysSum,
      },
    });
  }
}

return rows.length ? rows : [{ json: {} }];
