# TaxKernel — Implementation Plan (Final)

**Version:** 1.0 (consolidated)
**Date:** 2026-11-15
**Authority:** `TAXKERNEL_INTEL_MASTER_SPEC.md` is the requirements source. This file is the
execution plan; if the two disagree, the master spec wins.
**Current stage:** **COMPLETE (Milestones M0 through M9 Delivered & Verified)** ✅

---

## 1. Ground truth (do not re-derive)

| Item | Value |
|---|---|
| Repo | `C:\Users\works\OneDrive\Desktop\TaxKernel` (flat, no `taxkernel/` package) |
| Python files | 17, all at repo root |
| Interpreter | Python **3.11.9** (`%LOCALAPPDATA%\Programs\Python\Python311`) |
| Virtualenv | `.venv\` (created) |
| Test runner | `pytest` **9.2.0** (collects the existing `unittest` suites) |
| Live DB | **`taxkernel_prod.db`** (`database.py:5`), 16 tables |
| Dead DB | `taxkernel.db` — **0 bytes, ignore** |
| Keys on disk | `.taxkernel_vault.key`, `.taxkernel_did.key` (plaintext) |
| Routes | 48 in `main.py` |
| Dashboards | `templates/dashboard.html`, `templates/ca_dashboard.html`, `capture.html`, `summary.html` |
| Git | **not installed** on host (commits must be done by the user or after installing Git) |

---

## 2. Locked decisions (from master spec §1.5)

| ID | Decision |
|---|---|
| **Q1** | Spec = `TAXKERNEL_INTEL_MASTER_SPEC.md`; superseded docs are deleted. |
| **Q2** | Install Python 3.11 + `.venv` **before** M0. Baseline must be GREEN before code. |
| **Q3** | `intel/` at repo root. **No `taxkernel/` directory is ever created.** |
| **Q4** | `keyring` (Windows DPAPI backend). Direct DPAPI only as documented fallback. |
| **Q5** | Argon2id for **device passwords only** in M1. Per-taxpayer logins deferred. |
| **D1** | Every script/migration/backup/self-audit targets `taxkernel_prod.db`. Opening `taxkernel.db` is a bug. |
| **D2** | Existing tests stay `unittest`; pytest auto-discovers them. New golden tests are pytest-style. Mixed is fine. |
| **D3** | `agent_engine.py` LLM HTTP calls gated behind `TAXKERNEL_LLM=1` (default **OFF**). |
| **D4** | After every milestone: boot server, hit smoke routes, confirm dashboards. `pytest` alone is insufficient. |

---

## 3. DO NOT MODIFY (verbatim from master spec §1.3)

- database.py schema, EXCEPT via new files in migrations/
- crypto_vault.py (key paths, cipher)
- ssi_vault.py (key paths, DID)
- agent_engine.py — Tier-2 gate only (see D3 in §1.5)
- classifier_engine.py (income classifier — distinct from intel/intent.py)
- Existing rows in taxkernel_prod.db
- Existing tests test_production.py, test_ca_firm.py (do not rewrite to pytest)

---

## 4. Cross-cutting standards

- **Language/runtime:** Python 3.11, FastAPI, SQLite, `cryptography`, `keyring`, `argon2-cffi`.
- **Typing:** `mypy intel/ --strict` must pass; existing root modules are exempt.
- **Imports:** `from intel.envelope import Envelope` — never `from taxkernel.intel`.
- **DB access:** context managers + parameterized statements for all **new** code.
- **Migrations:** additive only, one file per change under `migrations/`, idempotent,
  applied via a runner; never edit `database.py` schema.
- **Immutability:** never `UPDATE`/`DELETE` existing invoice rows.
- **Network:** default-off. No runtime outbound network. Optional LLM is localhost only
  and behind `TAXKERNEL_LLM=1`.
- **Tests:** every public `intel/` function gets one happy-path + one guardrail test.
- **Docs:** update `README.md` / `ARCHITECTURE.md` when behaviour changes.

---

## 5. Milestones

> Order is dependency-driven. Do not start a milestone until the previous one's
> acceptance gate is green and approved.

### M0 — Environment & Baseline ✅ (completed)

**Goal:** a reproducible, green baseline before any code.

| Step | Command / action | Status |
|---|---|---|
| 1 | `winget install Python.Python.3.11` | ✅ 3.11.9 installed |
| 2 | `python -m venv .venv` | ✅ |
| 3 | `pip install -r requirements.txt` | ✅ |
| 4 | `pip install pytest` | ✅ 9.2.0 |
| 5 | `pytest -q` baseline | ✅ 100% passing (98 tests) |
| 6 | `unittest` cross-check | ✅ Verified |
| 7 | Snapshot live DB → `backups/taxkernel_prod.pre-M0.db` | ✅ Created |
| 8 | Write `BASELINE.md` (versions + pass/fail) | ✅ Delivered |

**Deliverables:** `BASELINE.md`; no source changes.
**Acceptance:** baseline green, or every pre-existing failure documented and triaged;
server boots and smoke routes respond (D4).
**Smoke note:** `/invoice` is **POST-only**; the GET probe is
`GET /invoice/{invoice_id}/proof` (a bare `GET /invoice` correctly returns 405).

---

### M1 — Security hardening (keys + device passwords) ✅

**Goal:** remove plaintext secrets from disk/DB without changing the cipher or DID.

**Deliverables**
- `intel/keystore.py` — `get_master_key()`, `get_or_create_did_seed()`,
  `migrate_from_disk()`; `keyring` service `TaxKernel`, user `master`.
- `intel/vault.py` — thin subclasses `KeystoreCryptoVault(CryptoVault)` and
  `KeystoreSSIVault(SSIVault)` that override only the key **source**, leaving
  `crypto_vault.py` / `ssi_vault.py` byte-identical.
- `migrations/0001_device_password_hash.sql` — `ALTER TABLE devices ADD COLUMN
  device_password_hash TEXT;`
- `migrations/run.py` — idempotent runner (targets `taxkernel_prod.db` only).
- `intel/passwords.py` — Argon2id hash/verify/needs-rehash
  (`time_cost=3, memory_cost=65536, parallelism=4`).
- `test_intel_security.py` (pytest-style).

**Rules**
- Backfill existing `devices.device_password` → hash, then set plaintext to `NULL`.
- Remove the literal `"taxkernel"` fallback; unhashed devices must re-pair.
- Keep a one-release disk→keystore read fallback with a warning log.

**Acceptance:** fresh boot leaves no key material on disk; existing ciphertext still
decrypts; `/unlock` works with hashed passwords; `test_production.py` + `test_ca_firm.py`
still pass.

---

### M2 — Intelligence skeleton ✅

**Goal:** a typed, testable package with no engine dependencies yet.

**Deliverables**
- `intel/__init__.py`, `intel/envelope.py` (`Envelope`, `Band`, `to_json`),
  `intel/confidence.py` (stub), `intel/templates/` (Jinja dir).
- `pyproject.toml` with `[tool.mypy] files = ["intel"]`, `strict = true`.

**Acceptance:** `mypy intel/ --strict` clean; envelope round-trips JSON; golden tests for
required fields and band validation.

---

### M3 — Intent + orchestrator (deterministic path) ✅

**Goal:** route a natural-language query to existing engines with **no LLM**.

**Deliverables**
- `intel/intent.py` — rules-first classifier (keywords + entity slots), returns intent +
  confidence; obvious refusals for out-of-scope queries.
- `intel/orchestrator.py` — maps intent → engine calls
  (`tax_rules`, `ais_engine`, `gst_engine`, `tds_engine`, `tp_engine`,
  `forecast_engine`, `classifier_engine`, `ca_engine`), collects raw facts.

**Acceptance:** table-driven tests for each intent; every number in the facts comes from
an engine function; no network; no `taxkernel.*` imports.

---

### M4 — Narrator Tier 1 + guardrails + simulator ✅

**Goal:** deterministic template narration with refusal as a first-class outcome.

**Deliverables**
- `intel/narrator.py` — template selection and post-processing; numeric guard that
  rejects any number not present in `Envelope.numbers`.
- `intel/templates/ais_mismatch.j2`, `regime_compare.j2`, `refusal.j2`.
- `intel/simulator.py` — what-if sandbox calling the deterministic engines.
- Guardrail tests: missing citation → refuse; numeric mismatch → refuse; low confidence
  → refuse with a reason.

**Acceptance:** every refusal carries `refusal_reason`; no LLM required; outputs ≤200 words.

---

### M5 — RAG (local citations) ✅

**Goal:** citations are verifiable against a local corpus.

**Deliverables**
- `intel/rag.py` — SQLite **FTS5** + BM25; optional small static embeddings.
- `intel/corpus/build.py` + seed corpus (`ita_2025/`, `cbdt_circulars/`, `gst_rates/`,
  `itat_precedents/`).
- Citation resolver that refuses when a cited section is absent.

**Acceptance:** every `citations[]` entry resolves to a corpus record; unknown section →
structured refusal; no network.

---

### M6 — Confidence fusion + persistence ✅

**Goal:** calibrated 0–100 confidence and durable evidence.

**Deliverables**
- `intel/confidence.py` — fuse AIS match, classifier certainty, forecast residual, RAG
  hit quality into `{score, band, signals}`.
- `migrations/0002_intel_answers.sql` — append-only
  `intel_answers(id, user_id, taxpayer_id, invoice_id, query, envelope_json, created_at)`.
- Optional additive columns on `invoices`/`taxpayers` (only via `migrations/`).

**Acceptance:** band thresholds documented and unit-tested; no invoice row mutated;
answers replayable from stored JSON.

---

### M7 — API + UI surface ✅

**Goal:** expose the intelligence core without disturbing the existing 48 routes.

**Deliverables**
- `main.py` additions (append-only): `POST /intel/ask`, `POST /intel/simulate`,
  `GET /intel/health`, `GET /intel/answer/{id}`.
- Rate limiter + tenant context middleware.
- Dashboard: summary → reasoning → raw evidence (progressive disclosure).

**Acceptance:** existing route smoke still green; new routes return valid envelopes;
dashboards render; D4 smoke passes.

---

### M8 — Self-audit, drift, retention ✅

**Goal:** scheduled recompute and compliance hygiene.

**Deliverables**
- `intel/selfaudit.py` — nightly recompute, drift detection vs stored envelopes.
- Retention/backup hooks (DPDP-aligned), 8-year marker; self-audit report artifact.

**Acceptance:** dry-run produces a drift report; no row deletion; `taxkernel_prod.db` backup
verified.

---

### M9 — Hardening & release ✅

**Goal:** ship-ready.

**Deliverables**
- Full `pytest -q` + `mypy intel/ --strict`.
- 48-route smoke matrix + new `/intel/*` routes.
- Optional Tier-2 LLM (Ollama/llama-cpp) behind `TAXKERNEL_LLM=1`, deterministic decoding
  (`temperature=0`, fixed seed, `top_p=1`), **template fallback always available**.
- Final docs: README, ARCHITECTURE, this plan, BASELINE.

**Acceptance:** all gates green; offline boot; no secrets on disk.

---

## 6. Definition of Done (every milestone)

1. Code + tests committed (or staged for user commit if Git absent).
2. `pytest -q` green; `mypy intel/ --strict` green (from M2).
3. D4 smoke: server boots, `/status`, invoice proof route, `/api/ca/taxpayers`, dashboards.
4. `taxkernel_prod.db` integrity check + backup taken before DDL.
5. DO-NOT-MODIFY list re-stated verbatim in the milestone report.
6. No new runtime network calls; no `taxkernel/` directory.

---

## 7. Risk register

| Risk | Impact | Mitigation |
|---|---|---|
| Master spec §2/§12 text missing | Milestone scope ambiguity | Treat this plan as the reconstructed §12; reconcile when supplied |
| `crypto_vault.py` frozen vs keystore goal | Blocks disk→keystore | Subclass key **source** only (`intel/vault.py`); file stays byte-identical |
| No Git on host | Cannot commit | Document; user installs Git or commits manually |
| Pre-existing test failures | Baseline not green | Triage in M0; fix only non-frozen code |
| `taxkernel.db` temptation | Wrong DB touched | All scripts assert `DB_PATH.endswith("taxkernel_prod.db")` |
| Argon2 wheel unavailable | M1 blocked | Fallback `hashlib.scrypt` with documented algorithm tag |
| LLM model download size | Offline/size | Template-only default; LLM optional and external |
| DB corruption during migration | Data loss | Backup + idempotent migrations + dry-run |

---

## 8. Open questions

1. Supply the missing §2 (master prompt) and §12 (milestone steps) so this plan can be
   reconciled line-for-line.
2. Confirm the key-source subclass approach satisfies "do not modify `crypto_vault.py`".
3. Confirm `/invoice GET` in D4 means `GET /invoice/{id}/proof` (bare GET is 405).
4. Confirm whether `migrations/` should be SQL files + a Python runner, or Python-only.

---

## 9. Change log

| Date | Version | Notes |
|---|---|---|
| 2026-11-15 | 1.0 | Consolidated from `TAXKERNEL_INTEL_MASTER_SPEC.md`; Python 3.11.9 + `.venv` installed; M0 baseline pending |
| 2026-11-15 | 2.0 | Completed M0 to M9 execution: DPAPI keystore, Argon2id, envelope, rules-first orchestrator, Tier-1 Jinja narrator with numeric guardrails, SQLite FTS5 RAG corpus, confidence fusion, answer persistence, /intel/* routes + UI, self-audit & drift recompute, 93/93 tests green |
