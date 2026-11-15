# ADAPTATION_REPORT.md

**Project:** TaxKernel (`C:\Users\works\OneDrive\Desktop\TaxKernel`)
**Date:** 2026-11-15
**Status:** DRAFT — **awaiting your approval. No code was written or modified.**
**Author:** OpenCode (analysis only)

---

## 0. CRITICAL FINDING — the named spec file is missing

`IMPLEMENTATION_TAXKERNEL_INTELLIGENCE.md` **does not exist** anywhere under `C:\Users\works`
(recursive search by name and by content returned nothing).

What *does* exist is `IMPLEMENTATION_PLAN.md`, which was **replaced today at 08:02**
with a document titled *"TaxKernel — Intelligence Layer & Hardening Implementation Spec"*
(`IMPLEMENTATION_PLAN.md:1`). That file is **only 169 lines** and **ends mid-sentence**
at `IMPLEMENTATION_PLAN.md:169`:

```python
169:     def to_json(self) -> dict: ...
```

So §4.2 is incomplete, and **§5 (DPDP?), §6 (new tables/schema), §7–§11
(milestones/tests) are absent**. The document itself points at the missing file:

> `IMPLEMENTATION_PLAN.md:14` — "Read `IMPLEMENTATION_TAXKERNEL_INTELLIGENCE.md` in full before writing code."

**Consequence:** everything below is based on the *available* §0–§4.2 of
`IMPLEMENTATION_PLAN.md`. Items that depend on the missing sections are marked
**⚠️ PROVISIONAL** and must be re-checked once you supply the real spec.

> **Action needed:** paste/sync the full `IMPLEMENTATION_TAXKERNEL_INTELLIGENCE.md`, **or**
> confirm that `IMPLEMENTATION_PLAN.md` is the intended spec and supply the rest of it.
> Note: the older "CA Firm Transformation" plan that used to live in this file is gone.

---

## 1. Repo inspection

### 1.1 Every `*.py` file (17 total)

| File | Bytes | Role |
|---|---:|---|
| `main.py` | 43,223 | FastAPI app, 48 routes, mDNS, WebSockets, templates |
| `database.py` | 29,079 | SQLite schema + all CRUD helpers (encrypt/decrypt at rest) |
| `crypto_vault.py` | 3,569 | AES-256-GCM field encryption + pairing PIN |
| `ssi_vault.py` | 5,226 | `did:key` + Verifiable Credential issue/verify |
| `agent_engine.py` | 7,405 | "Agentic" reasoning, hardcoded KB, optional local-LLM call |
| `classifier_engine.py` | 23,335 | Activity classification, retro switch, defense brief |
| `ais_engine.py` | 20,666 | AIS reconcile / drift / variance |
| `gst_engine.py` | 5,756 | GSTR-1/3B/9, ITC matching |
| `tds_engine.py` | 2,471 | TDS §393 rates / certificates |
| `tp_engine.py` | 3,127 | Transfer pricing / 3CEB / DTAA |
| `forecast_engine.py` | 8,401 | GST crossing, cash-flow, penalties, regime |
| `tax_rules.py` | 8,535 | Thresholds + slab math, 44ADA, advance tax, accrual |
| `ca_engine.py` | 7,004 | CA-firm bulk AIS, advance tax, audit package |
| `merkle_tree.py` | 2,792 | Hash tree for invoice immutability |
| `test_production.py` | 18,705 | `unittest` suite (line 1) |
| `test_ca_firm.py` | 5,450 | `unittest` suite (line 1) |
| `test_engine.py` | 6,664 | `unittest` suite (line 1) |

Also present: `templates/` (`dashboard.html`, `ca_dashboard.html`, `capture.html`,
`summary.html`), `Dockerfile`, `docker-compose.yml`, `requirements.txt`,
`run.ps1`, `load_all_data.ps1`, `taxkernel.db`, `taxkernel_prod.db`.

### 1.2 Database schema

Two important facts:

1. **`taxkernel.db` is 0 bytes** (empty file). `sqlite3 taxkernel.db ".schema"` would print
   nothing — the app never uses it.
2. `database.py:5` sets `DB_PATH = .../taxkernel_prod.db`. **`taxkernel_prod.db` (86 KB) is the
   live database.**
3. The `sqlite3` CLI is **not installed** on this host, so the schema was read with
   Node 26's built-in `node:sqlite` in **read-only** mode. No DB writes were made.

16 tables in `taxkernel_prod.db` (row counts in brackets):

| Table | Key columns (abridged) | Rows |
|---|---|---:|
| `users` | `id, name*, pan*, email*, created_at` (*encrypted) | 1 |
| `clients` | `id, user_id→users, name*, gstin*, created_at` | 1 |
| `financial_years` | `id, label UNIQUE, is_active` | 2 |
| `invoices` | `id, user_id, client_id, financial_year_id, vendor*, amount, date*, is_anomaly, supersedes_invoice_id, is_active, payment_state, payment_date, interest_charged, created_at` | 0 |
| `approvals` | `id, user_id, previous_hash, event_data*, current_hash, timestamp` | 1 |
| `devices` | `id, device_name, device_token UNIQUE, public_key, device_password (PLAINTEXT), created_at` | 0 |
| `merkle_roots` | `id, root_hash, signature, timestamp` | 0 |
| `ais_entries` | `id, source_name, amount, tds_deducted, section, created_at, taxpayer_id→taxpayers` | 0 |
| `purchases` | `id, user_id, vendor_name*, vendor_gstin*, taxable_amount, cgst, sgst, igst, date*, is_active` | 0 |
| `gstr2b_entries` | `id, vendor_gstin, taxable_amount, cgst, sgst, igst, invoice_date` | 0 |
| `tds_records` | `id, client_id, amount, section, rate, certificate_status` | 0 |
| `cross_border_tx` | `id, client_id, nature_of_tx, amount, country_code, arms_length_price` | 0 |
| `taxpayers` | `id, user_id→users, name*, pan*, gstin*, entity_type, status, assigned_staff` | 0 |
| `staff_members` | `id, name, email, role` | 0 |
| `notice_tracker` | `id, taxpayer_id, notice_section, notice_date, status, defense_brief*` | 0 |
| `sqlite_sequence` | SQLite internal | 4 |

Full `CREATE TABLE` DDL is in `database.py:18–240` (tables are created idempotently and
extended with `ALTER TABLE` migrations at `database.py:72–80, 106–109, 208–215`).

### 1.3 Every route in `main.py` (48)

| Line | Method | Path | Handler |
|---:|---|---|---|
| 147 | GET | `/pairing-pin` | `get_pairing_pin` |
| 152 | POST | `/pair` | `pair_device` |
| 163 | POST | `/unlock` | `unlock_device` |
| 173 | POST | `/invoice` | `add_invoice` |
| 240 | GET | `/status` | `get_status` |
| 285 | POST | `/approve` | `approve` |
| 350 | GET | `/credentials/issue` | `issue_credential` |
| 371 | GET | `/agent-reasoning` | `get_agent_reasoning` |
| 377 | GET | `/download-lut` | `download_lut` |
| 409 | GET | `/summary/qr` | `get_summary_qr` |
| 428 | POST | `/voice-entry` | `voice_entry` |
| 496 | GET | `/` | `get_dashboard` |
| 505 | GET | `/capture` | `get_capture` |
| 512 | GET | `/summary` | `get_summary` |
| 530 | GET | `/ca` | `get_ca_portal` |
| 548 | GET | `/did.json` | `get_did_document` |
| 575 | GET | `/invoice/{invoice_id}/proof` | `get_invoice_merkle_proof` |
| 599 | GET | `/compliance/itr4` | `generate_itr4_schema` |
| 634 | GET | `/compliance/gstr1` | `generate_gstr1_schema` |
| 670 | GET | `/compliance/itr-select` | `select_itr_form` |
| 710 | GET | `/compliance/tax-audit` | `get_tax_audit_status` |
| 736 | POST | `/invoice/{invoice_id}/escalate` | `escalate_invoice` |
| 778 | GET | `/invoice/{invoice_id}/irn` | `get_invoice_irn` |
| 815 | GET | `/compliance/arbitrage` | `get_tax_arbitrage` |
| 822 | GET | `/compliance/report` | `generate_audit_report` |
| 872 | POST | `/invoice/{invoice_id}/mark-paid` | `mark_paid` |
| 912 | POST | `/ais/import` | `import_ais` |
| 953 | GET | `/ais/reconcile` | `reconcile_ais` |
| 971 | GET | `/compliance/classify` | `classify_invoices` |
| 986 | GET | `/compliance/defense-brief` | `get_defense_brief` |
| 999 | POST | `/purchase` | `add_purchase_endpoint` |
| 1013 | GET | `/compliance/gstr3b` | `get_gstr3b` |
| 1019 | GET | `/compliance/gstr9` | `get_gstr9` |
| 1025 | POST | `/gst/import-2b` | `import_gstr2b` |
| 1031 | GET | `/compliance/tds-rates` | `get_tds_rate` |
| 1035 | POST | `/tds/record` | `record_tds` |
| 1045 | GET | `/tds/generate-certificate` | `generate_tds_cert` |
| 1051 | POST | `/tp/simulate` | `simulate_tp` |
| 1055 | POST | `/tp/generate-3ceb` | `generate_3ceb` |
| 1060 | GET | `/tp/dtaa-check` | `check_dtaa` |
| 1064 | POST | `/reset` | `reset_db` |
| 1073 | GET | `/api/ca/dashboard` | `get_ca_dashboard` |
| 1077 | GET | `/api/ca/taxpayers` | `get_ca_taxpayers` |
| 1081 | POST | `/api/ca/taxpayers` | `create_ca_taxpayer` |
| 1092 | POST | `/api/ca/bulk-ais-upload` | `bulk_ais_upload` |
| 1096 | GET | `/api/ca/advance-tax-summary` | `get_ca_advance_tax` |
| 1100 | GET | `/api/ca/defense-brief/{taxpayer_id}` | `get_ca_defense_brief` |
| 1104 | POST | `/api/ca/notices` | `log_ca_notice` |

### 1.4 `pytest -q` baseline — **BLOCKED (could not run)**

This host has **no Python interpreter** and **no test runner**:

| Command | Result |
|---|---|
| `python --version` | Microsoft Store alias stub ("Python was not found") |
| `py --version` | not recognized |
| `python3 --version` | Microsoft Store alias stub |
| `pytest --version` | not recognized |
| `sqlite3 --version` | not recognized |
| `.venv` | does not exist |
| Python in common install paths | none found |
| `docker` | not installed |

The suites are **standard-library `unittest`**, not pytest-native
(`test_production.py:1`, `test_ca_firm.py:1`, `test_engine.py:1`). pytest *can* collect
them, but it still needs Python + pytest installed.

**Baseline status: UNKNOWN / not established.** To establish it once Python 3.10+ is
available:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install pytest
.\.venv\Scripts\python.exe -m pytest -q
# existing runner also works:
.\.venv\Scripts\python.exe -m unittest test_production.py test_ca_firm.py test_engine.py
```

`mypy` is **not** in `requirements.txt` and no `mypy.ini`/`pyproject.toml` exists.

---

## 2. Five spec sections that conflict with existing code

Spec lines refer to `IMPLEMENTATION_PLAN.md` (the only spec present). Code lines are
exact.

### C1 — Package layout / tooling: `taxkernel/intel/` + `mypy taxkernel/` vs flat repo

- **Spec:** `IMPLEMENTATION_PLAN.md:15` ("`python -m mypy taxkernel/`"),
  `:29` ("every public function in `taxkernel/intel/`"), `:125` (`taxkernel/intel/` tree).
- **Code:** there is **no `taxkernel/` package**. Everything is flat at repo root and
  imported as top-level modules:
  `main.py:19` `import database`, `main.py:21` `from crypto_vault import CryptoVault`,
  `main.py:22` `from agent_engine import TaxKernelAgentEngine`, `database.py:3`
  `from crypto_vault import CryptoVault`.
- **Conflict:** a `taxkernel/intel/` tree cannot import root modules as `taxkernel.*`; and
  `mypy taxkernel/` has nothing to type-check. `mypy` is also absent from
  `requirements.txt:1–12`.

### C2 — "No network calls at runtime" vs live network + mDNS + HTTP LLM

- **Spec:** `IMPLEMENTATION_PLAN.md:25` ("No network calls at runtime.
  Everything ships in the repo…").
- **Code:**
  - `main.py:73–81` — `get_local_ip()` does `s.connect(("8.8.8.8", 80))` (external
    socket) on every `/status` and `/summary/qr` call (`main.py:276`, `:411`).
  - `main.py:84–101` — startup registers a **Zeroconf/mDNS** service on `:8000`.
  - `agent_engine.py:18` `self.local_llm_url = "http://localhost:1234/v1/chat/completions"`;
    `agent_engine.py:87` `requests.post(...)`; `requirements.txt:5` `requests`.
- **Conflict:** runtime does both external and localhost network I/O today.

### C3 — Deterministic decoding (`temperature=0`, seed, `top_p=1`) vs `temperature=0.2`

- **Spec:** `IMPLEMENTATION_PLAN.md:112–114` — "deterministic decoding
  (temperature=0, seed fixed, top_p=1)".
- **Code:** `agent_engine.py:87–94` posts
  `{"messages": [...], "max_tokens": 120, "temperature": 0.2}` — **temperature 0.2**,
  no `seed`, no `top_p` (`agent_engine.py:92`).
- **Conflict:** non-deterministic sampling; also the model's text is returned verbatim
  (`agent_engine.py:97–102`) with no numeric guard, contradicting the "LLM never
  produces a number" rule (`IMPLEMENTATION_PLAN.md:19–21`).

### C4 — OS keystore + HKDF per tenant vs raw key files on disk

- **Spec:** `IMPLEMENTATION_PLAN.md:108` — "Crypto: OS keystore-backed master key +
  HKDF per tenant".
- **Code:**
  - `crypto_vault.py:9` `KEY_FILE = .../.taxkernel_vault.key`; `:17–32`
    `_load_or_create_key()` reads/writes the raw AES-256 key to that file;
    `:15` one `self.aesgcm = AESGCM(self.master_key)` is used for **all** rows —
    **no HKDF, no per-tenant derivation**.
  - `ssi_vault.py:9` `KEY_FILE = .../.taxkernel_did.key`; `:17–34` writes an
    **unencrypted PEM** private key to disk.
- **Conflict:** keys are plaintext files on disk, not keystore-backed, and there is a
  single global key rather than per-tenant keys.

### C5 — "All new SQLite access uses context managers" vs bare connect/commit/close

- **Spec:** `IMPLEMENTATION_PLAN.md:27` — "All new SQLite access uses context managers
  and prepared statements."
- **Code:** `database.py:8–11` `get_db_connection()` returns a bare `sqlite3.Connection`;
  every helper manually does `conn = get_db_connection()` … `conn.commit()` …
  `conn.close()` with **no `with` block** — e.g. `add_invoice` at
  `database.py:292–311`, `add_device` at `:435–440`, `add_taxpayer` at `:616–644`.
- **Conflict:** no context-manager usage. (Queries are parameterized, so the
  "prepared statements" half is mostly satisfied.)

### Additional conflicts (not counted in the five)

- **A1 — RAG:** spec `:109` wants "SQLite-FTS5 + quantized embeddings (.gguf)";
  `agent_engine.py:7–13` is a hardcoded `OFFLINE_KNOWLEDGE_BASE` dict; no FTS5.
- **A2 — Citations/refusal:** spec `:24` "Every legal citation must exist in the local
  RAG index; if not, refuse"; `agent_engine.py:30–36` and `:131–135` return prose with
  **no citations** and no refusal path.
- **A3 — Numbers from LLM:** spec `:19–21` "LLM may NEVER … produce a number";
  `agent_engine.py:82` injects `₹{total:,.2f}` into the prompt and `:97–101` returns
  the model text unvalidated.
- **A4 — Secrets in schema:** `devices.device_password` is **plaintext**
  (`database.py:102`), compared with `==` at
  `database.py:442–452` and a hardcoded fallback `"taxkernel"` at `database.py:451`.
- **A5 — Test tooling:** spec `:15` says `pytest -q`; repo ships `unittest` only and no
  `pytest` in `requirements.txt:1–12`.

---

## 3. Proposed mapping: spec `taxkernel/intel/*` → repo `intel/*`

You asked for `intel/*` at repo root (not `taxkernel/intel/`). Keep the existing flat
modules untouched and add one new top-level package.

| Spec path (`taxkernel/intel/…`) | Proposed repo path (`intel/…`) | Notes |
|---|---|---|
| `__init__.py` | `intel/__init__.py` | exports `Envelope`, `orchestrate` |
| `envelope.py` | `intel/envelope.py` | `Envelope` dataclass + JSON (spec §4.2) |
| `intent.py` | `intel/intent.py` | rules-first, LLM fallback |
| `orchestrator.py` | `intel/orchestrator.py` | intent → engines → narrator |
| `narrator.py` | `intel/narrator.py` | template post-processor + guardrails |
| `confidence.py` | `intel/confidence.py` | signal fusion + banding |
| `rag.py` | `intel/rag.py` | BM25 + embeddings (see §6 deps) |
| `corpus/build.py` | `intel/corpus/build.py` | build-time indexer |
| `corpus/ita_2025/*.md` | `intel/corpus/ita_2025/*.md` | local statute text |
| `corpus/cbdt_circulars/*.md` | `intel/corpus/cbdt_circulars/*.md` | local circulars |
| `corpus/gst_rates/*.json` | `intel/corpus/gst_rates/*.json` | rate tables |
| `corpus/itat_precedents/*.md` | `intel/corpus/itat_precedents/*.md` | precedents |
| `templates/*.j2` | `intel/templates/*.j2` | `ais_mismatch.j2`, `regime_compare.j2`, `refusal.j2` |
| `simulator.py` | `intel/simulator.py` | what-if over deterministic engines |
| `selfaudit.py` | `intel/selfaudit.py` | nightly recompute / drift |
| `models/` | `intel/models/` | Ollama card + optional `.gguf` placeholder |

**Import strategy (recommended):** add `intel/` at repo root and import the existing
flat modules with plain imports (`import database`, `import tax_rules`, …). This works
as long as the process cwd/repo root is on `sys.path` (true for `uvicorn main:app` run
from the repo root, per `run.ps1:68`). Do **not** move existing modules into `taxkernel/`
in the first pass — that is a large, risky refactor.

**Optional hardening:** add a minimal `pyproject.toml` with `[tool.mypy]`
(`files = ["intel"]`) so `python -m mypy intel` works without touching root modules.

---

## 4. Modules that must NOT be replaced

The new `intel/` layer must **call** these, never reimplement or delete them. Their
public signatures are load-bearing for routes and tests.

**Explicitly named by you:**

| Module | Public contract that must survive | Used by |
|---|---|---|
| `agent_engine.py` | `TaxKernelAgentEngine(user_id)`, `.run_agentic_workflow(query)`, `.search_invoice_history()`, `.calculate_advance_tax(total)`, `.fetch_gst_notifications(query)` | `main.py:371–375` |
| `classifier_engine.py` | `classify_activity()` (l.202), `simulate_retroactive_switch()` (l.322), `generate_defense_brief()` (l.402) | `main.py:27, 971–998` |
| `crypto_vault.py` | `CryptoVault.encrypt/decrypt`, `generate_pairing_pin`, `get_current_pin`, `verify_pairing_pin`, `generate_device_token` | `main.py:34`, `database.py:6` |
| `ssi_vault.py` | `SSIVault.issue_verifiable_credential()`, `.verify_credential()`, `.did` | `main.py:35, 363–369, 548+` |

**Also must not be replaced (engine surface the intel layer will narrate):**

- `tax_rules.py` — thresholds/slabs/44ADA/advance tax/accrual (`:5–144`).
- `ais_engine.py` — AIS reconcile/draft/variance.
- `gst_engine.py`, `tds_engine.py`, `tp_engine.py` — compliance math.
- `forecast_engine.py` — GST crossing, cash-flow, penalties, regime.
- `ca_engine.py` — CA bulk AIS, batch advance tax, audit package.
- `merkle_tree.py` — invoice immutability proofs.
- `database.py` — schema + CRUD; extend, don't fork.
- `main.py` — all 48 routes/templates stay wired.
- `test_*.py` — existing `unittest` suites must keep passing.

**Guardrail:** the Orchestrator should import these engines and inject their numeric
output into the `Envelope.numbers` field; the Narrator only turns facts into prose.

---

## 5. Proposed migration plan

### 5.1 Keys: disk → OS keystore

**Current state**
- `crypto_vault.py:9` — `.taxkernel_vault.key` (raw 32-byte AES-256 key).
- `crypto_vault.py:17–32` — read/create raw key; `chmod 0600` is a no-op on Windows
  (`:27–31`).
- `ssi_vault.py:9` — `.taxkernel_did.key` (unencrypted PEM, `:17–34`).
- `crypto_vault.py:10` — `.taxkernel_pairing.pin` (plaintext PIN file).

**Target**
- Master key in **Windows Credential Manager** via `keyring` (service `TaxKernel`,
  user `master`), or DPAPI (`CryptProtectData`) via `ctypes` if you want zero extra deps.
- Per-tenant keys: `HKDF-SHA256(master, salt=tenant_salt, info=b"taxkernel-tenant:"+id)`
  (`cryptography` already present, so no new dependency).
- DID key: keep the PEM format but encrypt it under the master key (or store the raw
  seed in the keystore).

**Steps (idempotent, reversible)**
1. Add `intel/keystore.py` (or methods on `CryptoVault`) with
   `get_master_key()`, `put_master_key()`, `get_or_create_did_seed()`.
2. On startup: if `.taxkernel_vault.key` exists and keystore is empty → copy key into
   keystore, then best-effort shred the file (overwrite + delete) and write a
   `.migrated` marker.
3. Keep a one-release read fallback (disk → keystore) with a warning log; never write
   new keys to disk.
4. Add `taxpayerseed`/`tenant_salt` (see 5.3) and derive per-tenant keys lazily; cache in
   memory keyed by `user_id`.
5. Tests: fresh install writes nothing to disk; migration is idempotent; decrypt of an
   existing ciphertext still works after key move.

**Risk:** Credential Manager generic-blob limit is ~2560 bytes (32-byte key and ~230-byte
PEM are fine). Must not change ciphertext format, or all existing encrypted rows break.

### 5.2 Passwords: plaintext → argon2id

**Current state**
- `database.py:102` — `device_password TEXT` (plaintext).
- `database.py:435–440` — `add_device()` stores it verbatim.
- `database.py:442–452` — `verify_device_password()` does `row[0] == password_attempt`
  and falls back to the literal `"taxkernel"` (`:451`).
- `main.py:163–171` — `/unlock` calls it directly.

**Target:** `argon2-cffi` `PasswordHasher(time_cost=3, memory_cost=65536,
parallelism=4)`, PHC string stored in a new `device_password_hash` column.

**Steps**
1. Add `device_password_hash TEXT` to `devices` via idempotent `ALTER TABLE`
   (same try/except pattern as `database.py:106–109`).
2. Backfill: for each non-null `device_password`, compute hash → store in
   `device_password_hash`, then set `device_password = NULL`.
3. Update `add_device()` to hash; update `verify_device_password()` to
   `ph.verify(hash, attempt)` and `ph.check_needs_rehash()`.
4. Remove the `"taxkernel"` default fallback; if a device has no hash, force re-pair
   (return `None` → `main.py:167–168` already 403s).
5. Tests: correct/incorrect password, rehash on parameter change, legacy row migration,
   no plaintext remains.

**Toolchain note:** `argon2-cffi` ships prebuilt wheels for Windows/Python 3.10–3.13, so
no compiler is normally needed. If a wheel is unavailable, fall back to
`hashlib.scrypt` (stdlib) and record the algorithm in the PHC-like string.

### 5.3 Schema: new columns on `invoices` / `taxpayers`

**⚠️ PROVISIONAL — spec §6 is missing.** The proposal below is derived from the visible
architecture (HKDF per tenant, envelope evidence, calibrated confidence) and is
**additive only** (nullable, no row rewrites, respects the forensic-immutability rule at
`IMPLEMENTATION_PLAN.md:28`).

**`invoices` (append-only outputs; never `UPDATE` existing rows):**
- `intel_envelope_id TEXT` — FK to an `intel_answers` row (or JSON blob id).
- `intel_confidence INTEGER` — 0–100 snapshot.
- `intel_band TEXT` — `high|medium|low|refused` (CHECK).
- `rule_bundle_version TEXT` — engine/version set used.
- `evidence_hash TEXT` — Merkle/evidence reference.
- `narrative_template TEXT` — template id used when LLM absent.

**`taxpayers`:**
- `tenant_salt BLOB` — per-tenant HKDF salt.
- `keystore_ref TEXT` — opaque keystore handle (no key material).
- `intel_profile TEXT` — JSON (entity, regime, preferences).
- `dpdp_consent_at TEXT` — consent timestamp (DPDP Act 2023).
- `retention_until TEXT` — 8-year retention marker.
- `risk_score INTEGER` — dynamic audit-readiness score.

**Recommended extra table (instead of overloading `invoices`):**
`intel_answers(id, user_id, taxpayer_id, invoice_id, query, envelope_json, created_at)`
— keeps answers append-only and queryable while leaving invoice rows immutable.

**Mechanics**
- Add each column in `database.init_db()` with
  `try: cursor.execute("ALTER TABLE … ADD COLUMN …") except sqlite3.OperationalError: pass`
  (copy the existing pattern at `database.py:72–80`).
- No backfill required (all nullable).
- Bump `clear_db()` (`database.py:495–515`) if you add a new table.

### 5.4 Recommended order

1. Freeze a schema snapshot + copy `taxkernel_prod.db` to a backup (do this before any DDL).
2. Introduce `intel/keystore.py` and migrate keys (keep disk fallback).
3. Add argon2 hashing + backfill + tests.
4. Add the new columns/tables via idempotent `ALTER`s.
5. Add `intel/` skeleton (envelope, templates, orchestrator) wired to existing engines.
6. Only then: `pytest -q` / `mypy` gate, then the 48-route smoke test.

---

## 6. Dependencies needing a C++ toolchain or >100 MB download

| Dependency | Problem | Recommended substitute |
|---|---|---|
| `llama-cpp-python` | Compiles C/C++ (CMake + MSVC or gcc); no Python on host; Dockerfile installs `gcc` for this class of dep (`Dockerfile:12–16`) | **Ship template-only Narrator** (spec requires template fallback) and make Ollama an *optional external* runtime; do not add to base `requirements.txt` |
| Model files — Phi-3-mini-instruct-4k (~2.3 GB) / Qwen2-1.5B-Instruct (~1.1 GB) | Way over 100 MB; network download | Ship none in git; document optional `ollama pull`; keep `intel/models/` as a card + `.gitignore` |
| `sentence-transformers` + `torch` (CPU) | torch wheel ~200 MB–2.5 GB; C++/CUDA runtime | BM25 via `rank_bm25` (pure Python) + SQLite **FTS5**; optional tiny static embeddings (`model2vec`, ~30 MB) |
| `faiss-cpu` | C++ (wheels exist) but heavy; unnecessary for small local corpus | SQLite FTS5 + `numpy` cosine (`numpy` already in `requirements.txt:12`) |
| `chromadb` | Pulls DuckDB/onnxruntime, >100 MB, server-ish | SQLite FTS5 + `numpy`; store vectors as BLOB |
| `onnxruntime` | ~100–200 MB | Skip unless a specific embedding model demands it |
| `argon2-cffi` | C implementation, but **prebuilt wheels** exist for Windows/Py3.10–3.13 — *not* a toolchain risk | Keep `argon2-cffi`; fallback to stdlib `hashlib.scrypt` only if wheels fail |
| `cryptography` (already) | Wheels; no compiler needed | keep |
| `numpy` (already) | Wheels | keep |
| `pytest`, `mypy`, `keyring` | Pure Python; `keyring` Windows backend is `pywin32-ctypes` (no compiler) | keep |

**Recommendation:** keep base install wheel-only (`requirements.txt`), and put anything
heavier in an optional `requirements-intel.txt` (RAG/LLM extras). The product must remain
fully functional with **templates only** and no model file, per `IMPLEMENTATION_PLAN.md:116–117`.

---

## 7. Blockers / questions before coding

1. **Missing spec:** where is the full `IMPLEMENTATION_TAXKERNEL_INTELLIGENCE.md`? The
   present `IMPLEMENTATION_PLAN.md` stops at §4.2. §5–§11 (schema + milestones + tests)
   are required to finalize §5.3 and the build order.
2. **Toolchain:** may I install Python 3.10+ (e.g., via `winget`) and create `.venv` so
   the `pytest -q` baseline can actually run? If not, baseline stays UNKNOWN.
3. **Package root:** confirm `intel/` at repo root (your brief) **overrides** the spec's
   `taxkernel/intel/` (`IMPLEMENTATION_PLAN.md:125`).
4. **Keystore backend:** `keyring` (Windows Credential Manager) vs raw DPAPI via
   `ctypes` (zero deps)?
5. **Passwords:** is argon2id only for `devices.device_password`, or also for a new
   per-taxpayer login? Confirm parameters.
6. **Schema:** please confirm the exact new columns from §6; §5.3 is provisional.

---

## 8. What I did NOT do

- Did **not** create or modify any source file.
- Did **not** write to any database (opened `taxkernel_prod.db` read-only via `node:sqlite`).
- Did **not** install Python/pytest/anything.
- Did **not** re-run or alter `IMPLEMENTATION_PLAN.md` (it was already replaced on disk
  at 08:02 today).
- Only new artifact produced: this `ADAPTATION_REPORT.md`.

**→ Awaiting your approval (and the full spec) before any coding.**
