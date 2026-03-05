const item = $input.first();
const data = item.json;  // use .json so we get the payload object (keys "1","2",...), not the n8n item

return Object.values(data).map(record => ({
  json: record
}));
