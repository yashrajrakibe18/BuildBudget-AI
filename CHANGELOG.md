# Changelog

## 2.0.0 — 2026-11-26

### Added
- Full SaaS UI: 22 pages, design system, light/dark/system themes, collapsible sidebar, project
  switcher, global search, notification bell, responsive layout, skeletons, toasts, empty/error
  states and a compact expandable safety notice.
- Project workspace with Overview, Planning, Estimator, BOQ, Budget, Inventory, Procurement,
  Labour, Schedule, Documents, Reports and Activity tabs; project cards/table, archive/restore.
- Deterministic estimator expansion: geometry, openings, units, tile/paint/primer/brick/plaster/
  adhesive calculations with formulas, assumptions and wastage; add-to-BOQ with price refusal.
- Budget commitments/variance/alerts, duplicate invoice prevention, inventory transactions and
  low-stock alerts, supplier directory/prices/CSV import/delivered-cost comparison, purchase orders,
  labour, task dependencies, CPM and Gantt.
- Hybrid RAG: BM25 + hashed TF-IDF vectors with reciprocal rank fusion, optional
  sentence-transformers, duplicate detection, real page numbers only, citations, delete/reindex.
- ChatGPT-style assistant: persistent conversations, search/rename/pin/delete, project context,
  SSE operational events, Marked + DOMPurify Markdown, tool cards, approval cards, email preview,
  copy/regenerate/stop/retry.
- LangGraph supervisor + 12 specialists + verifier with structured routing, cross-agent findings,
  bounded iterations, 429 retries and honest failure messages.
- Real tool layer with schemas, permissions and audit rows; approval-gated writes that execute at
  most once.
- Mail Centre with folders, compose, CC/BCC, attachments, scheduling, approval-gated sending through
  SMTP (with implicit TLS), send-only Gmail API and a clearly labelled local capture provider,
  provider status, and explicit "mailbox sync unavailable" reporting.
- Notification centre with SSE, dedupe/retry, categories and preferences; automation centre with
  triggers, thresholds, recipients, schedules and run history.
- Analytics (OLS trend/forecast with MAE/MAPE, robust z-score anomalies, health/risk), branded PDF
  and styled Excel/CSV reports.
- PWA manifest, SVG icons and a static-assets-only service worker.
- `docs/ARCHITECTURE.md`, `docs/API.md`, this changelog and a rewritten README/status report.
- v2 tests for conversations, approvals-once, mail approval with a mock provider, hybrid RAG
  duplicate/delete, analytics insufficient-data and page/CSP rendering.
- Confirmation-gated demo reset (`scripts/reset_demo_data.py --confirm`) that deletes only
  `is_demo` projects and reseeds type-consistent scenarios; tested to preserve real projects.
- Composer paperclip now indexes a real document into the Knowledge Base (optionally project-linked)
  and reports its passage count instead of showing a "not implemented" modal.
- Mail Centre compose has a "Write with AI" panel: describe the email, pick an optional project and
  a tone, and the assistant fills Subject and Message from the same verified budget, inventory and
  schedule facts the coach uses. It never invents a recipient, no numbers come from the model, and
  the draft still needs the normal approval before anything is sent.

### Tests
- Added report-content tests (PDF text, workbook headers, frozen panes, INR formats, SUM formula)
  and demo-reset safety tests. Suite: 24 passed.

### Changed
- Split `app/api.py` into `app/api/` routers; split monolithic JS into `ui.js`, `app.js` and page
  modules; CSP-safe external scripts only.
- Dashboard and project rows now expose project status separately from budget status.
- Demo seed produces project-type-consistent BOQ, tasks, expenses and inventory.
- Dockerfile installs the PostgreSQL extra; CI runs ruff plus pytest; `pyproject.toml` version 2.0.0.

### Fixed
- SSE streams closed immediately because `request.is_disconnected` was checked synchronously
  (assistant and notifications); both are now async and read queues without blocking the loop.
- `/suppliers/compare` was shadowed by `/suppliers/{sid}`.
- ReportLab `build(canvasmaker=None)` call failed.
- Missing `ROLE_LABELS` import alias.
- LLM provider tool-call rejections leaked raw provider text into answers; they now retry once and
  degrade to a clean findings summary.
- Unused variables/ambiguous names and import order flagged by ruff.
- "Test connection" returned "Role 'Homeowner' cannot perform this action": the endpoint required
  the admin-only `mail.configure` capability, so project owners could not run it. It now requires
  `mail.send`, the same capability as composing and sending.
- `EMAIL_ENABLED` was only enforced for SMTP, so the local capture provider reported "ready" while
  the app still said sending was disabled. It is now the master switch for every provider.
- Compose rejected every save with a bare "A recipient is required." toast, even for a draft that
  does not need one yet, and never said which box was empty. Draft saves now work without a
  recipient; requesting approval focuses and marks the To field with a message that names it, and
  invalid To/Cc/Bcc addresses are rejected before they can reach an SMTP server.
- Mail Centre reported "Sending through LOCAL" for the capture provider as if mail were delivered;
  the banner now states that messages are written to `.run/mailbox` and are not delivered.

### Changed
- Assistant turns now carry the selected project into every LLM step (supervisor, specialists and
  verifier), not only into the tool context. "tell me about budget" with a project selected used to
  reply with a request for the project or a generic textbook answer; it now reads that project's
  budget, and a project-selection question is dropped from the plan whenever a project is selected.

### Removed
- The "Preliminary planning tool — structural work needs engineer-approved quantities" notice above every
  page (and its project-page variant) is gone; page content now starts directly under the page heading.

### Known gaps
- Gmail API mailbox sync is not implemented; outgoing send supports SMTP, Gmail API and local capture.
- No Alembic (additive startup migrations), no ChromaDB, no pandas/scikit-learn/Statsmodels,
  no OCR runtime, no Playwright suite in this delivery.
