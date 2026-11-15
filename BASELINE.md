# BASELINE — M0 Evidence

**Date:** 2026-11-15
**Milestone:** M0 — Environment & Baseline
**Status:** ✅ **GREEN**
**Repo:** `C:\Users\works\OneDrive\Desktop\TaxKernel`
**Requirements source:** `TAXKERNEL_INTEL_MASTER_SPEC.md` · **Plan:** `IMPLEMENTATION_PLAN.md`

---

## 1. Environment

| Item | Value |
|---|---|
| OS | Windows (host), `win32` |
| Interpreter | Python **3.11.9** (`%LOCALAPPDATA%\Programs\Python\Python311`) |
| Virtualenv | `.venv\` (repo-local, gitignored) |
| Shell | PowerShell |
| Git | 2.56.1 bundled with GitHub Desktop (not on `PATH`) |

### 1.1 Installed packages (`.venv`)

```
annotated-doc==0.0.6        httpcore==1.0.9             pytest==9.2.0
annotated-types==0.8.0      httpx==0.28.1               python-multipart==0.0.33
anyio==4.16.0               idna==3.20                  qrcode==8.2
certifi==2026.10.23         ifaddr==0.2.0               requests==2.34.2
cffi==2.1.1                 iniconfig==2.3.1            setuptools==65.5.0
charset-normalizer==3.5.2   Jinja2==3.1.6               starlette==1.10.0
click==8.5.1                MarkupSafe==3.0.4           typing_extensions==4.16.0
colorama==0.4.6             numpy==2.4.6                typing-inspection==0.4.5
cryptography==50.0.2        opentelemetry-api==1.45.2   urllib3==2.8.0
fastapi==0.163.0            packaging==26.3             uvicorn==0.54.0
h11==0.16.0                 pillow==13.0.0              websockets==17.4
                            pluggy==1.7.0               zeroconf==0.154.0
                            pycparser==3.12
                            pydantic==2.14.3
                            pydantic_core==2.50.4
                            Pygments==2.21.0
```

---

## 2. Database

| Item | Value |
|---|---|
| Live DB | `taxkernel_prod.db` — **86,016 bytes**, 15 tables |
| Dead DB | `taxkernel.db` — **0 bytes, ignored** (never opened by any code path) |
| Pre-M0 snapshot | `backups/taxkernel_prod.pre-M0.db` (86,016 bytes) |
| Integrity | live row counts **identical** to snapshot after the full test run |

| Table | Rows | | Table | Rows |
|---|---:|---|---|---:|
| `users` | 1 | | `purchases` | 0 |
| `clients` | 1 | | `gstr2b_entries` | 0 |
| `financial_years` | 2 | | `tds_records` | 0 |
| `invoices` | 0 | | `cross_border_tx` | 0 |
| `approvals` | 1 | | `taxpayers` | 0 |
| `devices` | 0 | | `staff_members` | 0 |
| `merkle_roots` | 0 | | `notice_tracker` | 0 |
| `ais_entries` | 0 | | | |

`sqlite_sequence` exists as the 16th table (SQLite internal).

---

## 3. Test results

### 3.1 `pytest -q`

```
......................                                                   [100%]
22 passed in 11.22s
```

### 3.2 `python -m unittest test_production test_ca_firm test_engine`

```
......................
----------------------------------------------------------------------
Ran 22 tests in 11.472s

OK
```

Suites: `test_production.py` (12), `test_ca_firm.py` (3), `test_engine.py` (7).
`test_production.py` and `test_ca_firm.py` were **not modified** (frozen per plan).

---

## 4. Boot smoke (D4)

Server: `uvicorn main:app --host 127.0.0.1 --port 8010` with
`TAXKERNEL_DB_PATH=<temp copy of the snapshot>` so the live ledger stayed untouched.

| Check | Method | Path | Code | Bytes |
|---|---|---|---:|---:|
| Root dashboard | GET | `/` | **200** | 14,286 |
| Status | GET | `/status` | **200** | 2,847 |
| CA dashboard | GET | `/ca` | **200** | 22,245 |
| Capture UI | GET | `/capture` | **200** | 5,082 |
| Summary UI | GET | `/summary` | **200** | 6,112 |
| CA taxpayers API | GET | `/api/ca/taxpayers` | **200** | 2 (`[]`) |
| Create invoice | POST | `/invoice` | **200** | 283 |
| Invoice proof | GET | `/invoice/1/proof` | **200** | 150 |
| Status after invoice | GET | `/status` | **200** | 3,210 |

Route count: **53** registered routes (the plan's "48" was the documentation-era count;
53 is the measured value including docs/openapi/websocket routes).

`POST /invoice` returns `{status, invoice_id, total, flags, is_anomaly, merkle_root, forecast}`.
`invoice_count` is exposed by `GET /status`, not by the POST response.

---

## 5. Blockers found and resolved

### 5.1 `zeroconf` native DLL blocked by Application Control

**Symptom**

```
ImportError: DLL load failed while importing multicast_outgoing_queue:
An Application Control policy has blocked this file.
```

`main.py` imported `zeroconf` at module scope, so `from main import app` failed — which
also broke `pytest` collection for all three suites.

**Root cause:** host security policy (WDAC / Application Control) blocks the
Cython-compiled `.pyd` modules shipped in `zeroconf` 0.154.0. Reproduced identically in
the old `TaxOS` venv, so it is environment-level, not caused by the fork or the rename.

**Fix (two layers)**

| Layer | Change | Scope |
|---|---|---|
| Environment | Renamed the 18 `zeroconf/**/*.pyd` files to `*.pyd.disabled`, forcing the shipped pure-Python fallbacks | `.venv` only (gitignored) |
| Code | Guarded `from zeroconf import ...` in `main.py` with `MDNS_AVAILABLE`; startup logs `mDNS disabled (...)` and returns instead of crashing | repo, permanent |

mDNS is LAN discovery only; the app is fully functional without it (bind by IP).

> A fresh venv will re-hit the DLL block, but the code guard now degrades gracefully to
> "mDNS disabled" instead of refusing to import.

### 5.2 `test_engine.py` was stale against the current APIs

Six failures were test drift, not product regressions:

| Test | Drift | Resolution |
|---|---|---|
| `test_database_invoice_operations` | `add_invoice(vendor, amount, date, is_anomaly)` → now needs `user_id, client_id, fy_id` | Test updated to current signature |
| `test_anomaly_detection_rules` | same signature change | Test updated |
| `test_44ada_tax_rules` | `res["estimated_tax"]` → now `new_regime_tax` / `old_regime_tax` | Test updated |
| `test_ledger_approvals_chain` | `get_approvals()` → now needs `user_id` | Test updated to compare against pre-existing chain |
| `test_server_invoice_endpoints` | expected `invoice_count` in `POST /invoice` response | Asserted via `GET /status` instead |
| `test_agent_reasoning_and_voice` | see 5.3 | Parser fixed, test kept |

### 5.3 Real bug: spoken-number parser

`POST /voice-entry` with `"invoice from Upwork of seventy-five thousand rupees"` returned
`1000.0`. The word map had no `seventy` and `split()` kept `"seventy-five"` as one token,
so only `thousand` matched (×1).

Fixed by adding `parse_spoken_amount()` in `main.py`: splits on non-letters, handles
units/teens/tens, and scales `hundred` / `thousand` / `lakh` / `lac` / `crore`.
`"seventy-five thousand"` → `75000.0`; digits still take precedence.

---

## 6. Test-isolation fixes (data-safety)

Both were required because `clear_db()` drops every table in whatever DB is bound.

1. **`test_engine.py`** now points `database.DB_PATH` at
   `%TEMP%\taxkernel_test_engine.db` in `setUpModule()` and deletes it in
   `tearDownModule()`. Before this, running the suite wiped the live ledger.
2. **`database.py`** `DB_PATH` now honours `TAXKERNEL_DB_PATH`:

   ```python
   DB_PATH = os.environ.get(
       "TAXKERNEL_DB_PATH",
       os.path.join(os.path.dirname(os.path.abspath(__file__)), "taxkernel_prod.db"),
   )
   ```

   Default behaviour is unchanged (`taxkernel_prod.db`); this is **not** a schema change.
   It enables smoke runs and future migrations against throwaway copies.

`test_production.py` / `test_ca_firm.py` may still touch the live DB when run directly;
they are frozen, so this is documented rather than changed. A pre-run snapshot exists at
`backups/taxkernel_prod.pre-M0.db`.

---

## 7. Files changed during M0

| File | Change |
|---|---|
| `main.py` | `zeroconf` import guarded (`MDNS_AVAILABLE`, `MDNS_IMPORT_ERROR`); startup skips mDNS when unavailable; added `parse_spoken_amount()` and wired it into `/voice-entry` |
| `database.py` | `DB_PATH` reads `TAXKERNEL_DB_PATH` env var (default unchanged) |
| `test_engine.py` | Rewritten against current APIs, kept `unittest`, added temp-DB isolation, added spoken-number assertions |
| `.gitignore` | already ignored `.venv/`, `*.db`, keys, `backups/` |

**DO-NOT-MODIFY list honoured:** `crypto_vault.py`, `ssi_vault.py`, `classifier_engine.py`,
`agent_engine.py` (gate only), database **schema**, existing DB rows, `test_production.py`,
`test_ca_firm.py` — all untouched.

---

## 8. Exit criteria

| Criterion | Result |
|---|---|
| `.venv` + dependencies reproducible | ✅ |
| `pytest -q` green | ✅ 22 passed |
| `unittest` cross-check green | ✅ 22 OK |
| Live DB snapshotted before any change | ✅ `backups/taxkernel_prod.pre-M0.db` |
| Live DB rows unchanged by test runs | ✅ verified table-by-table |
| Server boots | ✅ |
| `/status` responds | ✅ |
| Invoice proof route responds | ✅ `GET /invoice/1/proof` |
| `/api/ca/taxpayers` responds | ✅ |
| All four dashboards render | ✅ `/`, `/ca`, `/capture`, `/summary` |
| Pre-existing failures documented and triaged | ✅ §5 |
| `mypy intel/ --strict` | n/a (no `intel/` yet — gate opens at M2) |

**M0 verdict: GREEN — cleared to start M1.**
