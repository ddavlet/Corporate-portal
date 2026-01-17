# Setting up JSON Endpoint for Requests Page

The HTML page at `neuron.kolberg.uz/requests` needs a JSON endpoint at `neuron.kolberg.uz/requests-data`.

## Option 1: Create a New Workflow (Recommended)

1. Go to n8n at `https://dev.kolberg.uz`
2. Create a new workflow (or duplicate the existing "Table" workflow with ID `Q6bdnJV1MWuBUhtG`)
3. Add nodes in this order:

### Node 1: Webhook Trigger
- **Type**: Webhook
- **Path**: `neuron/requests-data`
- **Method**: GET
- **Response Mode**: "Respond to Webhook"

### Node 2: PostgreSQL - Requests
- **Type**: PostgreSQL
- **Operation**: Select
- **Table**: `requests`
- **Return All**: Yes
- **Credentials**: Use "Neuron_requests" credentials

### Node 3: PostgreSQL - Approvals
- **Type**: PostgreSQL
- **Operation**: Select
- **Table**: `approvals`
- **Return All**: Yes
- **Credentials**: Use "Neuron_requests" credentials
- **Execute Once**: Yes

### Node 4: PostgreSQL - Users
- **Type**: PostgreSQL
- **Operation**: Select
- **Table**: `users`
- **Return All**: Yes
- **Where**: (optional, or select all)
- **Credentials**: Use "Neuron_requests" credentials

### Node 5: Code - Format Data
- **Type**: Code
- **Language**: JavaScript
- **Code**:
```javascript
// Get data from previous nodes
const requests = $input.all().filter(item => item.json.table === 'requests' || item.json.id).map(item => ({ json: item.json }));
const approvals = $input.all().filter(item => item.json.request_id || item.json.approver_user_id).map(item => ({ json: item.json }));
const users = $input.all().filter(item => item.json.telegram_chat_id || item.json.role).map(item => ({ json: item.json }));

// Return formatted data
return [{
  json: {
    requests: requests,
    approvals: approvals,
    users: users
  }
}];
```

### Node 6: Respond to Webhook
- **Type**: Respond to Webhook
- **Respond With**: JSON
- **Response Body**: `={{ JSON.stringify($json) }}`
- **Response Headers**:
  - `Content-Type`: `application/json`
  - `Access-Control-Allow-Origin`: `*`

4. **Activate** the workflow
5. Test by visiting: `https://neuron.kolberg.uz/requests-data`

## Option 2: Modify Existing Workflow

You can modify the existing "Table" workflow (`Q6bdnJV1MWuBUhtG`) to support both HTML and JSON:

1. Add an IF node after the webhook to check the `Accept` header
2. If `Accept` contains `application/json`, format and return JSON
3. Otherwise, return HTML as it currently does

## Expected JSON Format

The endpoint should return:
```json
{
  "requests": [
    { "json": { "id": 1, "vendor": "...", "amount": 1000, ... } },
    ...
  ],
  "approvals": [
    { "json": { "id": 1, "request_id": 1, "decision": "approved", ... } },
    ...
  ],
  "users": [
    { "json": { "id": 1, "name": "...", "telegram_chat_id": "...", ... } },
    ...
  ]
}
```

## Testing

Once the endpoint is created:
1. Visit `https://neuron.kolberg.uz/requests-data` - should return JSON
2. Visit `https://neuron.kolberg.uz/requests` - should display the table with data
