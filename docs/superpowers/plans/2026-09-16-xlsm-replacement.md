# XLSM Replacement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Excel macro with a secure, persistent import inventory and export matching workbench.

**Architecture:** Keep FastAPI, Jinja, SQLAlchemy, SQLite, and Docker. Extend the existing upload-batch model into a durable workflow aggregate, persist background-job progress and planned allocations, and make preview/confirm/revert explicit transaction boundaries.

**Tech Stack:** Python 3.12, FastAPI 0.115+, Starlette sessions, SQLAlchemy 2, SQLite, Jinja, openpyxl, pytest, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-09-16-xlsm-replacement-design.md`

> **Requirement override (2026-09-16):** The customs operator confirmed that normalized Part Number equality is the only matching eligibility condition. Origin and date restrictions, the 720-day setting, and translated source-column labels are superseded by this decision. FIFO remains the allocation order.

## Global Constraints

- The exact supplied import/export workbooks and the macro inventory sheet must remain readable.
- Preview must never mutate inventory; confirm and revert must be atomic.
- Matching uses normalized Part Number as its only eligibility condition and FIFO as its allocation order.
- HS code, specification, unit, price, and amount are not match keys.
- No manual entry, personal accounts, import reversion, or automatic shortage retry.
- Tests must precede production changes and be observed failing for the intended reason.

---

### Task 1: Policy engine and allocation plan

**Files:**
- Create: `app/services/allocation_plans.py`
- Modify: `app/services/policy.py`
- Test: `tests/test_allocation_plans.py`

**Interfaces:**
- Produces `clean_part_number(value) -> str`.
- Produces `plan_export_rows(exports, lots) -> list[PlannedExport]` with allocation and shortage records.

- [ ] Write literal fixture tests for whitespace normalization, origin/date non-blocking behavior, FIFO tie-breaking, zero balance, split allocation, and shortage.
- [ ] Run `pytest tests/test_allocation_plans.py -q` and verify failures are caused by the missing module.
- [ ] Implement immutable planning dataclasses and the in-memory planner without database writes.
- [ ] Run the targeted tests, then `pytest -q`.
- [ ] Commit policy engine and tests.

### Task 2: Durable workflow schema and migrations

**Files:**
- Modify: `app/models.py`
- Modify: `app/db.py`
- Test: `tests/test_workflow_models.py`

**Interfaces:**
- Extend `UploadBatch` with source-file, processing, policy-snapshot, fingerprint, and reversion fields.
- Add `ProcessingJob` and `PlannedAllocation` models.

- [ ] Write schema tests proving fresh and existing SQLite databases contain the new fields and tables.
- [ ] Run the schema tests and observe missing-field failures.
- [ ] Add models and idempotent SQLite migration helpers; keep existing records readable.
- [ ] Run targeted and full tests.
- [ ] Commit schema and migration changes.

### Task 3: Streaming upload parsing, files, and jobs

**Files:**
- Create: `app/services/file_storage.py`
- Create: `app/services/jobs.py`
- Modify: `app/services/parsing.py`
- Test: `tests/test_upload_jobs.py`

**Interfaces:**
- Produces `store_upload(stream, filename) -> StoredUpload` with safe path, size, and SHA-256.
- Produces `enqueue_upload_job(batch_id) -> ProcessingJob` and `process_job(job_id)` using a new DB session.
- Produces streaming row readers for CSV/XLSX/XLSM.

- [ ] Write tests for safe filenames, file-size rejection, original-file redownload, progress persistence, restart-safe failure state, exact workbook header aliases, and VBA non-execution.
- [ ] Observe the targeted failures.
- [ ] Implement storage, streaming readers, and one persistent single-worker queue.
- [ ] Run targeted and full tests.
- [ ] Commit upload infrastructure.

### Task 4: Import review and export preview/confirm/revert

**Files:**
- Modify: `app/services/uploads.py`
- Modify: `app/services/matching.py`
- Modify: `app/routers/api.py`
- Test: `tests/test_workflows.py`

**Interfaces:**
- Add create/status/page/confirm endpoints for import batches and export matching batches.
- Add `POST /api/match-runs/{batch_id}/revert`.
- Disable direct matching mutations that bypass preview.

- [ ] Write tests proving exact duplicate imports are skipped, conflicts block the batch, preview is read-only, same-file exports cannot overbook, stale confirmation is rejected, partial confirmation emits shortage, and batch reversion restores exact balances once.
- [ ] Observe the intended failures.
- [ ] Implement preview persistence, inventory fingerprints, atomic confirm, and atomic logical reversion.
- [ ] Run targeted and full tests.
- [ ] Commit workflow behavior.

### Task 5: Shared authentication

**Files:**
- Create: `app/auth.py`
- Modify: `app/main.py`
- Modify: `app/routers/pages.py`
- Test: `tests/test_auth_and_settings.py`

**Interfaces:**
- Add `/login` and `/logout` endpoints.
- Read `APP_USERNAME`, `APP_PASSWORD_HASH`, and `SESSION_SECRET` from the environment.

- [ ] Write tests for PBKDF2 verification, protected routes, CSRF failures, secure session behavior, and throttled login.
- [ ] Observe the intended failures.
- [ ] Implement session authentication, CSRF, throttling, and persistent settings.
- [ ] Run targeted and full tests.
- [ ] Commit security and settings.

### Task 6: Concatenated workbook output

**Files:**
- Modify: `app/services/reports.py`
- Modify: `app/routers/api.py`
- Test: `tests/test_workbook_output.py`

**Interfaces:**
- Add `matching_run_workbook(db, batch_id) -> bytes`.
- Add authenticated original and result file download endpoints.

- [ ] Write tests for original export column repetition, FIFO allocation rows, partial `NO MATCH`, import-derived HS/specification, price/amount preservation, and the `원상태잔량` sheet.
- [ ] Observe the intended failures.
- [ ] Implement the workbook and authenticated downloads.
- [ ] Reopen generated workbooks and assert values and sheet names.
- [ ] Commit reports.

### Task 7: Operations workbench UI

**Files:**
- Modify: `app/templates/*.html`
- Modify: `app/static/styles.css`
- Modify: `app/static/app.js`
- Test: `tests/test_workbench_ui.py`

**Interfaces:**
- Pages: workbench, import review, export allocation review, inventory, history, settings, and login.

- [ ] Initialize 21st design context, search for a dense operations workbench pattern, and record the selected direction.
- [ ] Write route/UI tests for the two primary actions, progress polling, grouped expansion, pagination, shortage warning, confirmation, result download, and batch revert.
- [ ] Observe failures against the current UI.
- [ ] Implement the Jinja templates, CSS tokens, responsive states, accessible controls, and polling behavior.
- [ ] Run targeted/full tests and `21st review` for changed UI files.
- [ ] Commit the workbench UI.

### Task 8: Performance, deployment, and live verification

**Files:**
- Modify: `docker-compose.yml`
- Modify: `README.md`
- Modify: `SECURITY.md`
- Test: `tests/test_large_workflow.py`

**Interfaces:**
- Persist DB and uploads under `/data`.
- Configure shared login, session secret, and maximum upload bytes through environment variables.

- [ ] Write a synthetic 100,000-row import test proving background progress and paginated access without loading the full result into an HTTP response.
- [ ] Run the performance test and record measured duration and memory behavior.
- [ ] Update runtime configuration and operator documentation.
- [ ] Run the full suite, Docker build, and local browser workflow.
- [ ] Merge to `main`, push, monitor CI/CD, back up and reset the remote DB, execute the supplied-workbook smoke test, then reset the remote demo to empty.
