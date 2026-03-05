// Chunked version: output one n8n item per CHUNK of records (not one per record).
// This keeps memory lower and lets the next node process one chunk at a time.
const CHUNK_SIZE = 2000; // tune: 1000–5000 depending on memory

const item = $input.first();
const data = item.json;
const records = Object.values(data);

const chunks = [];
for (let i = 0; i < records.length; i += CHUNK_SIZE) {
  chunks.push(records.slice(i, i + CHUNK_SIZE));
}

return chunks.map(chunk => ({
  json: { chunk }
}));
