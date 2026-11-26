# API reference — BuildBudget AI 2.0

Base path: `/api/v1`. Interactive schema: `/docs` (Swagger UI) and `/openapi.json`.
All endpoints require a signed-in session unless marked public, and all project endpoints enforce
ownership. Unsafe methods require a same-origin request; the browser sends `X-CSRF-Token` from the
`csrf` meta tag.

Errors use `{"detail": "readable message"}` with `401` (not signed in / expired), `403` (role or
cross-origin), `404` (not found or not yours), `409` (conflict, duplicate, already decided),
`422` (validation) and `429` (rate limit).

## Auth (`/auth`)

| Method | Path | Purpose |
|---|---|---|
| POST | `/auth/register` | Create account (email, name, password, optional role) |
| POST | `/auth/login` | Sign in (`remember` extends server-side expiry) |
| POST | `/auth/logout` | Clear session |
| GET | `/auth/me` | Current profile |
| PATCH | `/auth/me` | Update name/email/preferences |
| POST | `/auth/password` | Change password |
| POST | `/auth/forgot-password` | Create reset token (no email enumeration) |
| POST | `/auth/reset-password` | Consume token and set password |

## Projects and workspace (`/projects`)

| Method | Path | Purpose |
|---|---|---|
| GET/POST | `/projects` | List (search, status, type, archived) / create |
| GET/PATCH/DELETE | `/projects/{pid}` | Detail / update / delete |
| POST | `/projects/{pid}/archive`, `/restore` | Archive or restore |
| GET | `/projects/{pid}/overview` | Workspace KPIs and recent activity |
| GET/POST | `/projects/{pid}/rooms` | Room measurements |
| POST | `/projects/{pid}/measure` | Geometry from dimensions/openings |
| GET/POST | `/projects/{pid}/estimates` | Saved estimates |
| GET/POST | `/projects/{pid}/boq` | BOQ lines |
| POST | `/projects/{pid}/boq/from-estimate` | Calculated quantity → BOQ (422 if no price) |
| POST | `/projects/{pid}/boq/approve` | Request BOQ approval |
| GET | `/projects/{pid}/budget` | Approved, estimate, actual, remaining, status, categories |
| GET/POST | `/projects/{pid}/expenses` | Expense history / record (409 duplicate invoice) |
| GET/POST | `/projects/{pid}/inventory` | Stock items |
| POST | `/projects/{pid}/inventory/{iid}/transactions` | Stock in/out/consume/adjust (422 negative) |
| GET/POST | `/projects/{pid}/tasks` | Tasks + CPM summary |
| PATCH/DELETE | `/projects/{pid}/tasks/{tid}` | Update/dependency validation |
| GET/POST | `/projects/{pid}/labour` | Labour entries |
| GET/POST | `/projects/{pid}/purchase-orders` | Procurement |
| GET | `/projects/{pid}/weather` | Open-Meteo advisory (when coordinates exist) |
| GET | `/projects/{pid}/reports/{name}.{fmt}` | PDF / XLSX / CSV report |
| GET | `/projects/{pid}/activity` | Project audit trail |

Global module views: `/boq`, `/budgets`, `/inventory`, `/procurement`, `/labour`, `/schedule`
return rows for all visible projects with optional `project_id` filtering, plus KPI blocks.

## Catalog and suppliers (`/suppliers`, `/materials`, `/material-prices`)

- Supplier CRUD, required-field validation, contact and tax fields.
- Material catalog CRUD.
- Price quotations with `source_type` (`demonstration`, `user_entered`, `quotation`, `historical`),
  validity dates, tax, delivery, MOQ and lead time.
- `POST /material-prices/import-csv` — preview/import with row validation and duplicate detection.
- `GET /suppliers/compare?material=...&quantity=...` — ranked delivered cost (unit price, tax,
  delivery, MOQ, expiry). Demo prices are labelled, never presented as market data.

## Knowledge (`/documents`)

| Method | Path | Purpose |
|---|---|---|
| POST | `/documents` | Upload PDF/DOCX/TXT/MD/CSV/XLSX; 422 on duplicate or unsupported type |
| GET | `/documents` | List with filters |
| GET | `/documents/stats` | Documents, chunks, backend, neural-embedding availability |
| GET | `/documents/search` | Hybrid search with citation metadata and confidence |
| GET | `/documents/{id}` | Metadata + readable passages |
| POST | `/documents/{id}/reindex` | Recount chunks |
| DELETE | `/documents/{id}` | Remove document **and** chunks |

Search hits include `document`, `document_id`, `page` (null when the format has none), `section`,
`version`, `source_url`, `excerpt`, `score`, `confidence` and `retrieval`.

## Assistant and approvals

| Method | Path | Purpose |
|---|---|---|
| GET | `/assistant/status` | Provider, model, availability, streaming mode |
| GET | `/assistant/models` | Provider/model catalog metadata (no keys) |
| GET/POST | `/assistant/conversations` | List/search conversations / new conversation |
| GET/PATCH/DELETE | `/assistant/conversations/{cid}` | Messages / rename or pin / delete |
| POST | `/assistant/chat` | Non-streaming turn |
| POST | `/assistant/stream` | SSE turn (see below) |
| GET | `/assistant/runs` | Agent run history |
| GET | `/assistant/tool-executions` | Audited tool calls |
| GET | `/approvals` | Approval requests (optional `status`) |
| GET | `/approvals/summary` | Counts by state |
| POST | `/approvals/{id}/decide` | `{"approve": true|false}`; 409 if already decided |
| POST | `/approvals/{id}/execute` | Retry an approved action that failed; never re-runs executed rows |

### SSE event contract

`POST /assistant/stream` with `{message, project_id?, conversation_id?}` returns
`text/event-stream`. Each event is `data: <json>` with one of:

```json
{"type":"status","message":"Understanding your request…"}
{"type":"routing","agents":["estimation"],"reason":"...","missing_info":[]}
{"type":"agent","agent":"estimation","status":"running|done|error"}
{"type":"tool","tool":"estimate_tile_quantity","status":"ok","duration_ms":12,"summary":"50 pcs of Tiles"}
{"type":"answer","answer":"...","agents":[...],"conversation_id":1,"message_id":9,"approvals":[],"tool_events":[...]}
{"type":"error","message":"..."}
{"type":"done"}
```

Keep-alive comments (`: keep-alive`) may arrive during long model calls. The final answer is a single
event; last-answer persistence happens server-side before it is emitted.

## Operations

- `GET /dashboard` — KPIs, series, project rows (`status` = project status, `budget_status` =
  budget health), health bands, insights, deadlines, overdue tasks.
- `GET /analytics` — series, trend, forecast, anomalies, budget risk, health, consumption, supplier
  performance, method notes.
- `GET /notifications`, `/notifications/stream` — list + SSE unread count.
- `POST /notifications/mark-read`, `/notifications/{id}/archive`, `/notifications/run-checks`.
- `GET /mail/status`, `/mail?folder=...`, `/mail/{id}`; `POST /mail/drafts`;
  `PUT/DELETE /mail/{id}`; `POST /mail/{id}/request-approval`; `POST /mail/{id}/send?confirm=true`;
  `POST /mail/{id}/schedule`; `POST /mail/test-connection`.
- `GET/POST /automations`, `PATCH/DELETE /automations/{id}`, `POST /automations/{id}/run`,
  `GET /automations/runs`.
- `GET /reports` catalog and `POST /reports/generate`.
- `GET/PATCH /settings`, `GET /settings/integrations`, `GET /meta`, `GET /activity`.
- `GET /health` and `/ready` are public; `/ready` checks the database connection.

## Rate limits

Assistant turns: 30/minute per user. Auth attempts and password reset are limited per IP/email.
Limits are in-process; a multi-worker deployment should move them to a shared store.
