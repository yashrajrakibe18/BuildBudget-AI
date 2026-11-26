# BuildBudget AI 2.0

A construction planning, cost-estimation, procurement and project-management platform with a
tool-using AI assistant. FastAPI + SQLAlchemy + Jinja2/ES6, LangChain + LangGraph multi-agent
orchestration, hybrid RAG, human approval before writes, PDF/Excel reporting and a separate
scheduler worker.

> **Scope notice.** BuildBudget AI is a preliminary planning tool, not a structural-engineering
> service. It never designs or certifies foundations, reinforcement, beams, columns, slabs or
> load-bearing walls, and never invents prices, quotations, citations or forecasts. Demonstration
> prices are synthetic and labelled. See [`DEVELOPMENT_STATUS.md`](DEVELOPMENT_STATUS.md) for an
> exact implemented / tested / not-implemented breakdown.

## What is in the box

**Workspace** — DB-driven dashboard with KPI tiles, expense trend, budget vs actual, category mix,
project health, AI insights computed from records, upcoming deadlines and overdue tasks; project
cards/table; project workspace with Overview, Planning, Estimator, BOQ, Budget, Inventory,
Procurement, Labour, Schedule, Documents, Reports and Activity tabs.

**Construction** — deterministic room geometry and unit conversion, tile/paint/primer/brick/
plaster/adhesive calculators with formula, assumptions and wastage, BOQ revisions and approval,
budget/expense tracking with duplicate-invoice rejection, inventory with transaction history and
no-negative-stock rule, supplier directory, price database, CSV import, delivered-cost comparison
(tax, delivery, MOQ, validity), purchase orders and deliveries, labour records and rates, task
dependencies, CPM critical path, Gantt view and Open-Meteo weather advisories.

**Intelligence** — hybrid retrieval (BM25 + hashed TF-IDF vectors, reciprocal rank fusion, optional
sentence-transformers), document ingestion with duplicate detection and real page numbers only,
branded PDF/Excel/CSV reports, analytics with OLS trend/forecast + held-out MAE/MAPE, robust
z-score anomaly flags and project health scoring. Functions say "insufficient data" instead of
inventing a forecast.

**AI assistant** — ChatGPT-style conversation sidebar, persistent conversations per user and
project, streaming SSE operational events, Markdown tables with DOMPurify, tool cards, approval
cards and email previews. A LangGraph supervisor routes to up to 12 specialist agents (planner,
estimation, budget, procurement, inventory, scheduling, research, analytics, reporting,
communication, approvals, general) that share one resolved project context. Tools are real Python
functions with Pydantic schemas, permission checks and audit rows.

**Communication & automation** — Mail Centre folders (drafts, pending approval, scheduled, sent,
failed), compose with CC/BCC/attachments, SMTP sending, approval-gated send, scheduling, APScheduler
rules for budget/stock/overdue/quotation/delivery triggers, notification centre and approval centre.
Sensitive actions never execute from the model directly.

## Stack

Python 3.12 · FastAPI/Uvicorn · Pydantic · SQLAlchemy 2 · SQLite (dev) / PostgreSQL (prod) ·
Jinja2 · Bootstrap-free custom design system with Lucide, Chart.js, Marked and DOMPurify ·
LangChain core / LangGraph · APScheduler · Open-Meteo · HTTPX · PyMuPDF · OpenPyXL · ReportLab ·
python-docx · pytest · ruff.

Deliberate choices where the original brief named a heavier component:

| Brief | This build | Why |
|---|---|---|
| ChromaDB | chunks in SQL, BM25 + hashed TF-IDF vectors fused with RRF, optional sentence-transformers | keeps user data transactional, per-user isolation, no model download or extra service on a 16 GB laptop; the retrieval interface is the same |
| Alembic | idempotent additive `ALTER TABLE` upgrades in `app/db_migrate.py` at startup | Alembic is not installed in this environment; additive upgrades preserve existing rows |
| Pandas / scikit-learn / Statsmodels / SciPy / OR-Tools | NumPy OLS, held-out metrics, median/MAD robust z-score, transparent rules | these packages are not installed here; the implemented methods are documented and honest about small samples |
| Gmail API OAuth | SMTP implemented; send-only Gmail API and local capture added; mailbox sync **unavailable** | no verified mailbox sync; no fake inbox is shown |
| OCR | optional flag only; scanned PDFs are rejected with a clear message | Tesseract is not installed |

## Setup (Windows PowerShell, uv)

```powershell
uv python install 3.12
uv sync --extra dev --extra groq        # or --extra google / --extra openai
Copy-Item .env.example .env             # fill in SECRET_KEY for anything beyond local dev
uv run python scripts/seed_demo_data.py # synthetic demo data (optional)
uv run python scripts/ingest_documents.py
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000>. API docs: <http://127.0.0.1:8000/docs>. Health: `/health`, readiness:
`/ready`.

`.env` is read when the process starts, so stop and start the server after changing it. Starting
with `uv run --env-file .env uvicorn ...` copies `.env` into the process environment once at launch;
the running server keeps those first values until it is restarted.

Demo login (only if you ran the seed): `demo@buildbudget.dev` / `DemoPass123` — change or delete it
before exposing the app.

To refresh only the synthetic scenarios (never real projects or the demo account):

```powershell
uv run python scripts/reset_demo_data.py --confirm              # delete + reseed demo projects
uv run python scripts/reset_demo_data.py --confirm --no-reseed  # delete demo projects only
```

Database upgrades are applied additively on startup. Back up `buildbudget.db` before upgrading an
existing installation (copy the file while the app is stopped).

Without uv: `pip install -e ".[dev,groq]"` and `python -m uvicorn app.main:app`.

### AI assistant

Set `LLM_PROVIDER` (`groq`, `google`, `openai`, `openrouter`), `LLM_MODEL` (a tool-calling model) and
the matching key in `.env`; install that provider's extra. Without a key the assistant endpoint
returns an honest "unavailable" state and the rest of the app works.

Use the paperclip in the composer to index a PDF/DOCX/TXT/MD/CSV/XLSX into the Knowledge Base (linked
 to the selected project when one is chosen), then ask about it; the document is retrieved through
hybrid RAG and cited.

Example prompts:

- "A room is 12 × 15 ft. How many 24 × 24 inch tiles with 10% wastage? Then list my projects."
- "Compare stored cement quotations for 20 bags, including delivery and tax."
- "Which projects are over budget, and what should I review?"
- "Draft a budget-warning email to the project manager" → approval card, sent only after approval.

Provider rate limits are real: the graph retries a 429 briefly, then reports that the step was
rate-limited instead of fabricating an answer. No token-level streaming is claimed; the UI streams
operational steps and delivers the final answer as one event.

### Email

1. Google Account → Security → 2-Step Verification → App passwords → create one.
2. Set `SMTP_USERNAME`, `SMTP_PASSWORD` (the app password — never your normal password),
   `SMTP_FROM_EMAIL`, `EMAIL_ENABLED=true`.
3. Test: `uv run python scripts/test_email.py`.
4. Sending from the Mail Centre or an approved AI draft uses SMTP, send-only Gmail API when configured,
   or the clearly labelled local capture provider. Gmail API inbox sync is **not** implemented.
5. `EMAIL_ENABLED` is the master switch for every provider, including local capture. Without a
   mailbox (`EMAIL_ENABLED=false`), use `EMAIL_ENABLED=true` + `MAIL_PROVIDER=local` to capture
   messages as `.eml` files in `.run/mailbox` — that proves the whole send path without delivering
   anything to a real recipient.

### Scheduler (one process only)

```powershell
uv run python scripts/run_scheduler.py
```

Keep `SCHEDULER_IN_APP=false`; run exactly one worker. Free hosts that sleep cannot guarantee timely
alerts. Notifications are deduplicated by alert key and retried up to three times.

### Tests and lint

```powershell
uv run pytest -q
uv run ruff check app scripts tests
```

CI (`.github/workflows/ci.yml`) runs ruff and pytest on push/PR. The suite uses a temporary SQLite
database and a scripted fake LLM: it verifies routing, real tool execution, approval-once, mail
approval with a mock provider and page rendering. It does **not** measure live model quality and
does not call paid providers.

## Docker / PostgreSQL

```powershell
docker compose up --build
```

The image installs the `postgres` extra. `docker-compose.yml` starts PostgreSQL, the web app and one
scheduler. Change the sample database password and provide `SECRET_KEY` in `.env` before any real
deployment. Set `DATABASE_URL=postgresql+psycopg://...` and run the app once so tables are created.

## Project layout

```
app/
  main.py            app shell, pages, security headers, PWA routes
  models.py          SQLAlchemy models (projects, BOQ, expenses, suppliers, inventory,
                     labour, tasks, documents/chunks, conversations, approvals, mail,
                     automations, notifications, activity, tool executions)
  database.py        engine/session + schema creation
  db_migrate.py      additive column upgrades (no destructive migrations)
  core/              config, security, permissions, labels, rate limiting
  api/               REST routers (auth, workspace, catalog, knowledge, assistant, ops)
  services/          business logic shared by REST and AI tools
  ai/                llm, tools_*, graph (supervisor → specialists → verifier)
  templates/         22 Jinja2 pages
  static/            design system CSS, JS modules, PWA manifest, service worker
  workers/           APScheduler jobs
scripts/             seed, ingest, scheduler, email test
tests/               pytest suite
docs/                architecture and API reference
```

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) and [`docs/API.md`](docs/API.md).

## Safety and data

- Roles enforced server-side: administrator, project manager, site engineer, accountant,
  procurement manager, viewer, plus read-only analyst.
- Same-origin/CSRF checks on unsafe methods, SameSite=Lax session cookie, server-side session
  expiry, strict CSP with no inline scripts, upload type/size validation.
- AI writes create approvals; approval execution is guarded by `executed_at` so it runs at most
  once. Approval state is read from the database, never from model text.
- Retrieved document text is wrapped as untrusted context; the assistant is instructed never to
  follow instructions found in documents.
- Do not commit `.env`, the SQLite database or generated reports. `.gitignore` covers them.
