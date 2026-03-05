{
    "nodes": [
        {
            "parameters": {},
            "type": "n8n-nodes-base.manualTrigger",
            "typeVersion": 1,
            "position": [
                -304,
                -16
            ],
            "id": "c703c4af-fa29-4887-9601-ffd727bb0640",
            "name": "When clicking ‘Execute workflow’"
        },
        {
            "parameters": {
                "url": "http://146.158.94.97:5869/ajax/modules/service/",
                "options": {}
            },
            "type": "n8n-nodes-base.httpRequest",
            "typeVersion": 4.3,
            "position": [
                32,
                -16
            ],
            "id": "9ea25d80-fbd8-48e3-870f-3133b38d14fc",
            "name": "HTTP Request"
        },
        {
            "parameters": {
                "jsCode": "const ZONE = 'Asia/Tashkent';\n\n// --- helpers ---\nfunction replaceText(value, from, to) {\n  if (value === null || value === undefined) return value;\n  return String(value).split(from).join(to);\n}\n\nfunction textBeforeDelimiter(value, delim = '-') {\n  if (value === null || value === undefined) return null;\n  const s = String(value);\n  const idx = s.indexOf(delim);\n  return idx === -1 ? s.trim() : s.slice(0, idx).trim();\n}\n\nfunction parsePrice(val) {\n  if (val === null || val === undefined) return 0;\n  const s = String(val).trim().replace(',', '.');\n  const n = Number(s);\n  return Number.isFinite(n) ? n : 0;\n}\n\nfunction parseDateTimeRU(val) {\n  if (!val) return null;\n  const s = String(val).replace(/\\s+/g, ' ').trim(); // normalize spaces\n  const dt = DateTime.fromFormat(s, 'dd.MM.yyyy HH:mm', { zone: ZONE });\n  return dt.isValid ? dt : null;\n}\n\n// --- input ---\n// NEW: items = [{json:{...record1}}, {json:{...record2}}, ...]\nconst records = $input.all()\n  .map(i => i.json)\n  .filter(v => v && typeof v === 'object');\n\n// --- transform ---\nlet rows = records.map(v => {\n  const doctors = v.user_name ?? null;\n  const patients = v.fio ?? null;\n\n  const amount = parsePrice(v.price);\n\n  const dt = parseDateTimeRU(v.date);\n  const revenue_date = dt ? dt.setZone(ZONE).toISO({ suppressMilliseconds: true, includeOffset: true }) : null;\n  const revenue_time = dt ? dt.startOf('hour').toFormat('HH:mm:ss') : null;\n\n  const payment_method = v.payment_method ?? null;\n  const payment_type = payment_method === 'Наличными' ? 'Наличная оплата' : 'Безналичная оплата';\n\n  let service_group = v.group_name ?? null;\n  service_group = replaceText(service_group, 'Группа', 'Лаборатория');\n  service_group = replaceText(service_group, 'Медикаменты', 'Операция');\n\n  let service_title = v.title ?? null;\n  service_title = replaceText(service_title, 'ЛФК-Лечебная физкультура стационарная', 'Травматолог-Консультация');\n  service_title = replaceText(service_title, 'ЛФК-Лечебная физкультура амбулаторная', 'Травматолог-Консультация');\n  service_title = replaceText(service_title, 'ЛФК-ЛФК', 'Травматолог-Консультация');\n\n  let service_category = textBeforeDelimiter(service_title, '-');\n  service_category = replaceText(service_category, 'Алгология', 'Нейрохирургические операции');\n  service_category = replaceText(service_category, 'Колопроктология', 'Хирургические операции');\n  service_category = replaceText(service_category, 'Группа', 'Лаборатория');\n  service_category = replaceText(service_category, 'ЛФК', 'Травматолог');\n\n  let year = null, month = null, quarter = null;\n  if (dt) {\n    year = dt.year;\n    month = dt.month;\n    quarter = Math.floor((dt.month - 1) / 3) + 1;\n  }\n\n  return {\n    id: v.id !== undefined && v.id !== null ? Number(v.id) : null,\n    client_id: v.client_id !== undefined && v.client_id !== null ? Number(v.client_id) : null,\n    doctors,\n    patients,\n    amount,\n    payment_method,\n    payment_type,\n    revenue_date,\n    revenue_time,\n    service_title,\n    service_group,\n    service_category,\n    year,\n    month,\n    quarter,\n  };\n});\n\n// optional sort (only makes sense if the batch contains multiple items)\nrows.sort((a, b) => {\n  const da = a.revenue_date ? DateTime.fromISO(a.revenue_date).toMillis() : 0;\n  const db = b.revenue_date ? DateTime.fromISO(b.revenue_date).toMillis() : 0;\n  return db - da;\n});\n\n// output as n8n items\nreturn rows.map(r => ({ json: r }));\n"
            },
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [
                576,
                -16
            ],
            "id": "e2f1ba63-76c1-468a-ae7c-7b1c64a54275",
            "name": "Code in JavaScript"
        },
        {
            "parameters": {
                "operation": "upsert",
                "schema": {
                    "__rl": true,
                    "mode": "list",
                    "value": "public"
                },
                "table": {
                    "__rl": true,
                    "value": "revenues",
                    "mode": "list",
                    "cachedResultName": "revenues"
                },
                "columns": {
                    "mappingMode": "autoMapInputData",
                    "value": {},
                    "matchingColumns": [
                        "id"
                    ],
                    "schema": [
                        {
                            "id": "id",
                            "displayName": "id",
                            "required": false,
                            "defaultMatch": true,
                            "display": true,
                            "type": "number",
                            "canBeUsedToMatch": true
                        },
                        {
                            "id": "client_id",
                            "displayName": "client_id",
                            "required": false,
                            "defaultMatch": false,
                            "display": true,
                            "type": "number",
                            "canBeUsedToMatch": false
                        },
                        {
                            "id": "doctors",
                            "displayName": "doctors",
                            "required": false,
                            "defaultMatch": false,
                            "display": true,
                            "type": "string",
                            "canBeUsedToMatch": false
                        },
                        {
                            "id": "patients",
                            "displayName": "patients",
                            "required": false,
                            "defaultMatch": false,
                            "display": true,
                            "type": "string",
                            "canBeUsedToMatch": false
                        },
                        {
                            "id": "amount",
                            "displayName": "amount",
                            "required": true,
                            "defaultMatch": false,
                            "display": true,
                            "type": "number",
                            "canBeUsedToMatch": false
                        },
                        {
                            "id": "payment_method",
                            "displayName": "payment_method",
                            "required": false,
                            "defaultMatch": false,
                            "display": true,
                            "type": "string",
                            "canBeUsedToMatch": false
                        },
                        {
                            "id": "payment_type",
                            "displayName": "payment_type",
                            "required": false,
                            "defaultMatch": false,
                            "display": true,
                            "type": "string",
                            "canBeUsedToMatch": false
                        },
                        {
                            "id": "revenue_date",
                            "displayName": "revenue_date",
                            "required": false,
                            "defaultMatch": false,
                            "display": true,
                            "type": "dateTime",
                            "canBeUsedToMatch": false
                        },
                        {
                            "id": "revenue_time",
                            "displayName": "revenue_time",
                            "required": false,
                            "defaultMatch": false,
                            "display": true,
                            "type": "time",
                            "canBeUsedToMatch": false
                        },
                        {
                            "id": "service_title",
                            "displayName": "service_title",
                            "required": false,
                            "defaultMatch": false,
                            "display": true,
                            "type": "string",
                            "canBeUsedToMatch": false
                        },
                        {
                            "id": "service_group",
                            "displayName": "service_group",
                            "required": false,
                            "defaultMatch": false,
                            "display": true,
                            "type": "string",
                            "canBeUsedToMatch": false
                        },
                        {
                            "id": "service_category",
                            "displayName": "service_category",
                            "required": false,
                            "defaultMatch": false,
                            "display": true,
                            "type": "string",
                            "canBeUsedToMatch": false
                        },
                        {
                            "id": "year",
                            "displayName": "year",
                            "required": false,
                            "defaultMatch": false,
                            "display": true,
                            "type": "number",
                            "canBeUsedToMatch": false
                        },
                        {
                            "id": "month",
                            "displayName": "month",
                            "required": false,
                            "defaultMatch": false,
                            "display": true,
                            "type": "number",
                            "canBeUsedToMatch": false
                        },
                        {
                            "id": "quarter",
                            "displayName": "quarter",
                            "required": false,
                            "defaultMatch": false,
                            "display": true,
                            "type": "number",
                            "canBeUsedToMatch": false
                        },
                        {
                            "id": "created_at",
                            "displayName": "created_at",
                            "required": false,
                            "defaultMatch": false,
                            "display": true,
                            "type": "dateTime",
                            "canBeUsedToMatch": false
                        }
                    ],
                    "attemptToConvertTypes": false,
                    "convertFieldsToString": false
                },
                "options": {}
            },
            "type": "n8n-nodes-base.postgres",
            "typeVersion": 2.6,
            "position": [
                1184,
                112
            ],
            "id": "02fdd571-e3f3-4027-8b57-b55cb6b9c0a7",
            "name": "insert revenues",
            "credentials": {
                "postgres": {
                    "id": "YXvWoKdEZBm6fktV",
                    "name": "Neuron_requests"
                }
            }
        },
        {
            "parameters": {
                "batchSize": 100,
                "options": {}
            },
            "type": "n8n-nodes-base.splitInBatches",
            "typeVersion": 3,
            "position": [
                944,
                -16
            ],
            "id": "93828afb-25ac-4483-a7a1-75c67807cae0",
            "name": "Loop Over Items"
        },
        {
            "parameters": {
                "jsCode": "const data = $input.first();\n\nreturn Object.values(data).map(item => ({\n  json: item\n}));"
            },
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [
                304,
                -16
            ],
            "id": "5674b195-9077-425f-8f44-794253ae4414",
            "name": "Code in JavaScript1"
        },
        {
            "parameters": {},
            "type": "n8n-nodes-base.noOp",
            "typeVersion": 1,
            "position": [
                1152,
                -112
            ],
            "id": "aa47b926-5c48-4131-b6f5-02a8f4a07f1b",
            "name": "No Operation, do nothing"
        }
    ],
        "connections": {
        "When clicking ‘Execute workflow’": {
            "main": [
                [
                    {
                        "node": "HTTP Request",
                        "type": "main",
                        "index": 0
                    }
                ]
            ]
        },
        "HTTP Request": {
            "main": [
                [
                    {
                        "node": "Code in JavaScript1",
                        "type": "main",
                        "index": 0
                    }
                ]
            ]
        },
        "Code in JavaScript": {
            "main": [
                [
                    {
                        "node": "Loop Over Items",
                        "type": "main",
                        "index": 0
                    }
                ]
            ]
        },
        "insert revenues": {
            "main": [
                [
                    {
                        "node": "Loop Over Items",
                        "type": "main",
                        "index": 0
                    }
                ]
            ]
        },
        "Loop Over Items": {
            "main": [
                [
                    {
                        "node": "No Operation, do nothing",
                        "type": "main",
                        "index": 0
                    }
                ],
                [
                    {
                        "node": "insert revenues",
                        "type": "main",
                        "index": 0
                    }
                ]
            ]
        },
        "Code in JavaScript1": {
            "main": [
                [
                    {
                        "node": "Code in JavaScript",
                        "type": "main",
                        "index": 0
                    }
                ]
            ]
        }
    },
    "pinData": {
        "When clicking ‘Execute workflow’": [
            {}
        ]
    },
    "meta": {
        "templateCredsSetupCompleted": true,
            "instanceId": "aaa5eb3b3bb2b0e4c2900ebf2061149fc2bf8ef76f120e9fd24b91ca24d47211"
    }
}
