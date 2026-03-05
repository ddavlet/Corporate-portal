# MedPlus n8n workflow – easing load for huge HTTP responses

## Current flow (from structure.js)

1. **Manual Trigger** → **HTTP Request** (single URL, returns one huge object `{"1":{...},"2":{...},...}`).
2. **Code in JavaScript1** (codenode1): `Object.values(data).map(...)` → one n8n **item per record** (e.g. 500k items).
3. **Code in JavaScript** (codenode2): `$input.all()` → loads **all** items, transforms and **sorts** everything, then returns all.
4. **Loop Over Items** (SplitInBatches 100) → **insert revenues** (Postgres) → loop until done.

## Why this hurts with huge data

- **Memory**: Full dataset lives in memory several times (raw HTTP body, then N items after Code1, then Code2 holds the whole set).
- **Single burst**: One Code2 run over the entire set and one big in-memory sort.
- **Server load**: High peak CPU/memory for that one run.

---

## What you can do

### 1. **Chunk early and process per chunk (recommended)**

- **Code1**: Don’t output one item per record. Output **one item per chunk** of records (e.g. 2000 records per item).  
  Use `codenode1_chunked.js`: it outputs items like `{ json: { chunk: [record1, record2, ...] } }`.
- **Before Code2**: Add a **Split In Batches** node with **batch size 1** (so Code2 receives one chunk at a time).
- **Code2**: Process only that one chunk (one item with `item.json.chunk`).  
  Use `codenode2_chunked.js`: it reads `$input.first().json.chunk`, transforms and sorts only that chunk, and returns items for the DB.
- **Keep** the existing **Loop Over Items** (e.g. 100) → **insert revenues** after Code2.

Result: Code2 and the engine never hold the full dataset in memory; only one chunk (e.g. 2000 records) is in memory at a time. Sort is per chunk, so much cheaper.

**Workflow change:**

- Replace Code1 with the logic in `codenode1_chunked.js`.
- Insert **Split In Batches** (batch size **1**) between Code1 and Code2.
- Replace Code2 with the logic in `codenode2_chunked.js`.
- Connect: Code1 → Split In Batches (chunks) → Code2 → Loop Over Items (100) → insert revenues → back to Split In Batches (chunks).

You can tune `CHUNK_SIZE` in `codenode1_chunked.js` (e.g. 1000–5000) based on memory.

---

### 2. **Server-side pagination (if the API supports it)**

If `http://146.158.94.97:5869/ajax/modules/service/` supports `?page=1&limit=1000` (or similar):

- Use a **Loop** or **Split In Batches** to run multiple HTTP requests (page 1, 2, 3, …).
- Process each page (e.g. with current or chunked Code2) and insert.
- This reduces response size per request and spreads load; you never hold the full response in one go.

---

### 3. **Reduce work inside Code2**

- **Drop the sort** if the DB or reports don’t rely on global order (chunked Code2 only sorts within chunk).
- **Strip unused fields** in Code1 so fewer keys are carried (e.g. only what Code2 and the DB need).

---

### 4. **Postgres batching**

- You already use **Loop Over Items** with batch size 100. If the DB handles it, try 250–500 to reduce round-trips; don’t go so high that a single batch times out.

---

### 5. **Schedule and limits**

- Run the workflow in off-peak times.
- If the API allows, request only recent data (e.g. date range) so the payload is smaller.

---

## File reference

| File | Role |
|------|------|
| `codenode1.js` | Current: one item per record (heavy when dataset is huge). |
| `codenode1_chunked.js` | Chunked: one item per chunk of records; use with Split In Batches (1) before Code2. |
| `codenode2.js` | Current: processes all items with `$input.all()`. |
| `codenode2_chunked.js` | Chunked: processes single item `{ json: { chunk: [...] } }` only. |

Using the chunked pair plus one **Split In Batches (1)** before Code2 is the main change that eases computation and server load when the HTTP request returns a huge dataset.
