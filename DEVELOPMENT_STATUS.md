# Development status — BuildBudget AI 2.0

Snapshot: 26 November 2026. This file is deliberately conservative: anything not verified is listed
as such.

## Verification actually run in this build

| Check | Result |
|---|---|
| `pytest -q` | **24 passed**, 1 warning (LangGraph `create_react_agent` deprecation) |
| `ruff check app scripts tests` | **All checks passed** |
| `node --check` on every JS file | Passed |
| OpenAPI schema | 109 paths / 137 operations |
| Server + browser | Uvicorn on `127.0.0.1:8010`; login, dashboard, projects, project overview/BOQ/schedule, assistant stream exercised in the packaged Chromium |
| Live LLM smoke (Groq, owner's key) | Tile question routed to `estimation`, tool executed, answer contained **50 tiles**; general chat and multi-turn conversation saved |
| Acceptance numbers | 180 sq ft room + 24 in tiles + 10% → 50; room geometry 12×15×10 ft → floor 180, gross wall 540; BOQ from estimate 50×60+18% → ₹3,540; CPM 4-task chain → 9 days; delivered cost MOQ 10×400+18%+₹500 → ₹5,220 |
| Report content | BOQ PDF text contains branding, project name, line description and the structural-scope note; XLSX has frozen headers, wide description column, INR number formats and a SUM total formula |
| Composer attachment | Uploaded a Markdown file from the assistant composer via the real API: indexed, reported 1 passage, then deleted the smoke document |

Not run: real SMTP delivery (no credentials), real scheduled execution on a clock, Playwright/mobile
viewport automation, OCR, PostgreSQL, Docker build, and visual review of every PDF/Excel layout.
Those are **not** claimed as tested.

## Implemented and tested

**Foundation**
- Auth: PBKDF2 hashing, signed HttpOnly session, server-side expiry (12 h / 30 d), role checks,
  password reset tokens, profile and password change, read-only role blocked from writes.
- Per-user isolation for projects, conversations, approvals, mail, documents, notifications and
  tool executions; foreign IDs return 404.
- CSRF same-origin check + optional token, strict CSP, security headers, upload allow-list/size
  limit, generic 500 responses, rate limits, audit/activity log.
- Additive startup migrations that preserve existing rows.

**Application**
- 22 pages with a custom responsive design system, light/dark/system theme, collapsible sidebar,
  breadcrumbs, project switcher, notification bell, global search, toasts, modals, skeletons,
  empty/error states, accessible focus styles. No inline scripts (CSP-safe).
- Human-readable labels for internal codes, readable timestamps, currency formatting; raw JSON only
  in the optional debug view.
- Dashboard KPIs and charts from the database, filters, computed insights, deadlines and overdue
  work. Project status and budget status are separate fields so "Active" is never shown as "Ok".
- Projects: cards/table, search/filter/sort, create/edit/archive/restore, project workspace tabs,
  page title uses the project name.
- Estimator: geometry, openings, units, tiles/paint/primer/bricks/plaster/adhesive, wastage,
  formulas/assumptions, save, add to BOQ (refuses without a price), scenarios.
- BOQ revisions and approval, budget actuals/committed/utilization/variance, expenses with duplicate
  invoice rejection, inventory transactions without negative stock, supplier comparison by delivered
  cost, procurement, labour, task dependencies/CPM/Gantt, weather advisory.
- Knowledge base: drag/drop upload, indexing status, duplicate detection, readable passages, hybrid
  search, citations with real page numbers only, delete removes chunks, reindex.
- Reports: branded PDF (header/footer/page numbers/scope notes), styled Excel (freeze panes,
  filters, INR/date formats, summary + detail), CSV. BOQ, budget, expenses, inventory, procurement,
  labour, progress and full project summary where implemented in `services/reporting.py`.
- Analytics: OLS trend/forecast with held-out MAE/MAPE, robust z-score anomalies, health scoring,
  budget-risk projection, material consumption, supplier performance; explicit "insufficient data"
  results.
- Notifications: persistent, deduplicated, retried, categories/priority, read/archive, SSE unread
  count, budget/stock/overdue/quotation checks. A long-standing bug where the SSE loop checked
  `request.is_disconnected` synchronously (always truthy) was fixed.
- Approvals: persisted, expiring, approve/reject, exactly-once execution, execution error recorded,
  approval centre with before/after values.
- Mail: folders, compose with CC/BCC/attachments, draft/edit/delete, schedule, pending-approval,
  failed state, SMTP provider, provider test, approval-gated send. Sending never happens from the
  model. Outgoing providers now include SMTP (with implicit-TLS/port-465 support), send-only Gmail API
  (OAuth refresh-token based) and a clearly labelled local capture provider; mailbox sync is still **not**
  implemented and no fake inbox is shown.
- Automations: rules with triggers/thresholds/recipients/templates/schedule/approval flag, run
  history, APScheduler worker, idempotency and dedupe.
- AI assistant: persistent per-user conversations, search/rename/pin/delete, project context,
  welcome/suggested prompts, SSE operational steps, Markdown rendered with Marked + DOMPurify, tool
  cards, approval cards, email preview, copy/regenerate/stop/retry, timestamps. The composer
  paperclip indexes a real PDF/DOCX/TXT/MD/CSV/XLSX into the Knowledge Base (project-linked when a
  project is selected) and reports the passage count; the assistant retrieves it through RAG.
- LangGraph supervisor + 12 specialists + verifier, structured routing, shared tool context,
  cross-agent findings, bounded iterations, provider retries, honest rate-limit failures.
- Real tools across project, estimation, BOQ/budget, suppliers/procurement, inventory, scheduling,
  RAG, analytics, reporting, mail, approvals and notifications, each with a schema, permission check
  and audit row.
- PWA: manifest, SVG icons, service worker caching static assets only.
- Demo reset: `scripts/reset_demo_data.py` requires `--confirm`, deletes only `is_demo` projects and their children, keeps real projects, the demo account and shared catalog, then reseeds the type-consistent scenarios. Verified on a copy of the real database: 5 demo projects replaced, the real project kept, the painting scenario contains no tile lines.

## Implemented but not live-tested

- **SMTP delivery**: logic and approval path tested with a mock provider; no real mailbox was
  contacted. Provider acceptance ≠ confirmed recipient delivery.
- **Scheduler firing on a real clock**: jobs and dedupe logic are unit/integration tested; the
  worker process was not left running for a full interval.
- **PDF/Excel visual output**: generation and content are tested (branding, project name, rows,
  frozen panes, INR formats, total formula), but not pixel layout across every report type.
- **Gmail App Password setup**: documented but not exercised here.
- **PostgreSQL/Docker**: configuration provided; the build ran on SQLite only.

## Requires credentials or external services

- LLM: `LLM_PROVIDER`, `LLM_MODEL`, matching key, provider extra. Without it the assistant returns
  503 "unavailable" by design.
- SMTP: Gmail App Password (never the normal password) or another SMTP host, `EMAIL_ENABLED=true`.
- Gmail API inbox sync: **not available** in this build (OAuth 2.0 mailbox implementation absent). Outgoing send is available via SMTP and, when configured, Gmail API.
- Open-Meteo works without a key; coordinates are optional, and absence is reported.
- PostgreSQL production: `DATABASE_URL=postgresql+psycopg://...` and `uv sync --extra postgres`.

## Known limitations

- **No Alembic.** `app/db_migrate.py` adds missing columns idempotently at startup; there is no
  downgrade path. Back up `buildbudget.db` before upgrading.
- **No ChromaDB and no bundled embedding model.** Retrieval is BM25 + hashed TF-IDF with RRF;
  sentence-transformers is used only if separately installed. Hashed vectors do not generalise like
  neural embeddings.
- **No pandas/scikit-learn/Statsmodels/OR-Tools.** Analytics use NumPy OLS and median/MAD; this is
  documented in the UI method notes. Forecasts need enough history and are labelled preliminary.
- **No OCR.** Scanned PDFs are rejected with an explanation; `ENABLE_OCR` is a placeholder.
- **Existing v1 demo database** in the delivered workspace predates the scenario rewrite. The seed
  script now produces type-consistent BOQ/tasks/expenses/inventory for fresh installs, but the old
  demo rows are left untouched to avoid destroying user data. Run
  `python scripts/reset_demo_data.py --confirm` to replace only those synthetic scenarios.
- **No organizations/project members**, no Gmail-style threading/inbox sync, no Microsoft Graph, no
  report charts in PDF beyond summary tables (ReportLab layout is branded but simple).
- Rate limits are in-process, so multiple web workers each get their own budget.
- Groq's free-tier tokens-per-minute limit can rate-limit multi-specialist turns; the UI reports
  that a step was rate-limited rather than inventing an answer.
- LangGraph emits a deprecation warning for `create_react_agent`; it still works with the installed
  version and is kept behind a compatibility import.

## Setup

```powershell
uv python install 3.12
uv sync --extra dev --extra groq
Copy-Item .env.example .env
uv run python scripts/seed_demo_data.py
uv run python scripts/ingest_documents.py
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
# second terminal, exactly one instance:
uv run python scripts/run_scheduler.py
```

Demo account after seeding: `demo@buildbudget.dev` / `DemoPass123`.

## Pending / continuation plan

1. Decide on Alembic (or keep additive migrations) and add a tested downgrade/backup workflow.
2. Implement Gmail API mailbox sync (least-privilege scopes, encrypted token storage, sync/threading) or
   explicitly drop Gmail from the roadmap in the UI copy.
3. Add Playwright tests for login, project creation, estimator, assistant stream, approval and mail
   at desktop/tablet/mobile widths.
4. Add PDF/Excel golden-file checks and visual review of every report type.
5. Optionally run `scripts/reset_demo_data.py --confirm` on the existing installation to refresh the
   older v1 demo projects (left untouched during this delivery to avoid deleting records).
6. Optionally add neural embeddings behind a feature flag, evaluated against the hashed baseline.
7. Add a shared-store rate limiter and structured request IDs for multi-worker deployments.
