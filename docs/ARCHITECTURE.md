# Architecture — BuildBudget AI 2.0

## 1. Shape of the system

```
Browser (Jinja2 shell + ES6 modules)
   │  JSON REST + SSE
   ▼
FastAPI routers (app/api/*)
   │  auth / ownership / CSRF / rate limits
   ▼
Services (app/services/*)  ◄──────────── AI tools (app/ai/tools_*.py)
   │                                      │ same service functions
   ▼                                      ▼
SQLAlchemy models ──────────────── SQLite (dev) / PostgreSQL (prod)
   ▲
APScheduler worker (scripts/run_scheduler.py) — one process
```

The REST layer and the assistant call the **same** service functions, so the model can never do
something the website cannot. Services own validation and persistence; routers only translate HTTP.

## 2. Request lifecycle

1. `SessionMiddleware` reads the signed `bb_session` cookie.
2. `current_user` checks `uid` and the server-side `exp` timestamp (12 h, or 30 days with
   "keep me signed in") and loads the user.
3. Unsafe methods pass a same-origin `Origin`/`Referer` check and, when present, an `X-CSRF-Token`
   comparison against the session token. Browsers always send `Origin` cross-site, so this blocks
   CSRF before the token check.
4. Every project-scoped route calls `owned_project`, and every list/query filters by `owner_id`
   (admins excepted). Foreign IDs return 404 rather than leaking existence.
5. Responses receive CSP, `X-Frame-Options`, `nosniff`, referrer and permissions headers. API
   responses are `no-store` (streams excluded).

Page routes render one shell template per page; the page-specific ES6 module fetches JSON and builds
DOM nodes. There are no inline scripts or `onclick` attributes, matching the strict CSP
(`script-src 'self' https://cdn.jsdelivr.net https://unpkg.com`). Markdown from the model is rendered
with Marked and sanitised with DOMPurify.

## 3. Frontend modules

- `theme.js` — resolves light/dark/system before first paint to avoid flashes.
- `ui.js` — `BB.*` formatting (currency, dates, labels), API client with CSRF header and error
  toasts, data tables, modals, drawers, badges, charts, skeletons, empty/error states.
- `app.js` — sidebar, project switcher, notification poll, search, account menu.
- `pages/*.js` — one module per page; `project.js` + `project-modules.js` render workspace tabs.
- `pwa.js` + `sw.js` — service worker caches **static assets only**; API, HTML and documents stay
  network-only so user data is never served from a shared cache.

## 4. AI orchestration

```
START → supervisor ──(missing info)──────────────► finish → END
             │
             └──► specialists (bounded, shared ToolContext)
                        planner / estimation / budget / procurement / inventory /
                        scheduling / research / analytics / reporting / communication /
                        approvals / general
                                  │
                                  ▼
                                finish (verifier) → END
```

- **Supervisor** uses `with_structured_output(SupervisorPlan)` (falling back to JSON extraction)
  and chooses specialists from `AGENTS`; it never routes by keyword.
- **Specialists** are LangGraph `create_react_agent` instances with a per-agent tool subset. They
  receive bounded history (last 6 messages, 2 000 chars each) plus any findings earlier specialists
  produced in the same turn (`ToolContext` also shares the resolved project id).
- **Verifier** writes the final answer using only specialist outputs, keeps tool-derived numbers,
  cites knowledge passages only when present and points to the approval panel when something is
  pending. If the provider rejects the call it retries once with a no-tools instruction; if that
  fails it returns the findings without provider errors or stack text.
- Iterations are bounded (`recursion_limit`, `LLM_MAX_AGENTS`), provider 429s are retried twice with
  backoff, and model reasoning is never exposed — only status, routing, tool and agent events.
- Streaming uses a worker thread + queue + SSE. The generator is async and awaits
  `request.is_disconnected()`; a previous synchronous check was always truthy and closed streams
  early (fixed).

**Tool contract:** each tool is a `StructuredTool` with a Pydantic schema. `ToolRegistry` enforces
project context, role capability, validates Python inputs and writes a `tool_executions` audit row
(args, result preview, status, duration). Errors are returned to the model as data
(`{"error": "..."}`), not raised as stack traces. Write tools create `ApprovalRequest` rows.

**Approval exactly-once:** `approvals.decide` reserves the decision by committing `status=approved`,
executes the action, then stores `executed_at`. A second decision sees a non-pending status and is
rejected; a retry of an approved-but-failed action goes through `execute_approved`, which refuses if
`executed_at` is set. Editing a draft after approval clears it back to `draft` in the mail flow.

## 5. Retrieval (hybrid RAG)

```
upload → extension/size validation → text extraction (real page numbers only)
       → cleaning → section-aware chunks (900 chars, 150 overlap)
       → documents + chunks (content hash per owner prevents duplicates)
query  → BM25 scores ─┐
       → vector scores ├─ reciprocal rank fusion → term-coverage rerank → top-k
       → hashed TF-IDF (512 dims) or optional sentence-transformers
```

Retrieved passages carry document, version, page (or `null`), section, source metadata and a
confidence relative to the best hit. `wrap_untrusted()` delimits text so documents cannot act as
instructions. Deleting a document deletes its chunks in the same transaction. PDFs without
extractable text are rejected unless OCR is deliberately enabled; DOCX/XLSX never invent page
numbers.

## 6. Data model (main entities)

Users · projects · rooms/measurements · estimations · BOQ items (revisioned) · expenses ·
materials · suppliers · material prices · inventory items/transactions · purchase orders/items ·
labour rates/entries · tasks/task dependencies · documents/chunks · conversations/messages ·
agent runs · tool executions · approval requests · email drafts · automation rules/runs ·
notifications · activity log · password reset tokens.

All project data hangs off `projects.owner_id`; approval, mail, conversation and tool rows also
carry `user_id`. Duplicate invoices are prevented by the expense uniqueness rule; duplicate documents
by `(owner_id, content_hash)`; notification dedupe by `alert_key`; mail send by `sent_at` /
status plus approval `executed_at`.

## 7. Migrations and compatibility

`app/db_migrate.py` runs at startup after `create_all` and adds missing columns with idempotent
`ALTER TABLE ... ADD COLUMN` statements. It never drops or rewrites existing data. This replaces
Alembic in this environment (Alembic is not installed); see DEVELOPMENT_STATUS for the trade-off and
backup guidance.

## 8. Analytics and reporting

- Trend: OLS on monthly totals (needs ≥3 non-zero months).
- Forecast: OLS with a held-out tail; MAE/MAPE reported (needs `FORECAST_MIN_MONTHS`, default 6).
- Anomalies: robust z-score using median/MAD (≥5 expenses), explicitly "a flag, not proof".
- Health/risk: transparent weighted rules and constant-burn projection.
- Reports: ReportLab PDF with brand header/footer/page numbers and scope notes; OpenPyXL with
  styled headers, widths, freeze panes, filters, INR/date formats, summary + detail sheets; CSV
  exports. Figures come from stored data only.

## 9. Automation

APScheduler runs in a dedicated process. Rules have trigger, threshold, recipients, template,
schedule, timezone and approval-required flag. Runs are recorded, alerts deduplicated by
`alert_key`, email retries capped, and a failure is stored instead of silently swallowed. Running
multiple workers with `SCHEDULER_IN_APP=true` would duplicate sends, so it defaults to off.

## 10. Security posture

PBKDF2 password hashing · server-side role checks · session rotation on login · SameSite=Lax +
HttpOnly session cookie (`Secure` in production) · CSRF same-origin + token · strict CSP · DOMPurify
for model Markdown · upload allow-list, size limit and content-type checks · no path traversal in
attachments (paths come from generated reports) · API keys never sent to the browser · provider
tokens never logged · untrusted-document wrapping · bounded agent iterations · rate limiting on
chat and auth · generic 500 responses with server-side logging · `.env`, DB, reports and venv
excluded from Git.

## 11. Performance choices

Lazy imports for LLM providers and sentence-transformers; no ML model at startup; hashed vectors
computed per query (small corpora); pagination on list endpoints; SQL aggregates for dashboard KPIs;
bounded conversation history; configurable `RAG_TOP_K`; Chart.js instances destroyed on re-render;
static assets cacheable/versioned by the service worker. No background indexing queue: uploads index
synchronously and report the chunk count.
