# PLAN_M0 — Environment & Baseline

**Milestone:** M0
**Status:** ✅ Complete (evidence: [`BASELINE.md`](BASELINE.md))
**Depends on:** nothing
**Blocks:** every other milestone

---

## 1. Objective

Establish a reproducible, **green** baseline before a single line of intelligence-layer
code is written. M0 produces no product features — it produces *trust*: a known Python
environment, a passing test suite, a snapshotted database, and proof that the server boots
and serves every dashboard.

**Rule:** if M0 is not green, do not start M1.

---

## 2. Scope

### In scope
- Python 3.11 interpreter + repo-local virtualenv
- Dependency installation from `requirements.txt` + `pytest`
- Test suite execution (pytest **and** the original unittest runner)
- Database snapshot + row-level integrity check
- Boot smoke of the existing routes and dashboards (decision **D4**)
- Triage/fix of pre-existing test failures
- `BASELINE.md` evidence file

### Out of scope
- Any `intel/` code
- Any schema change
- Any change to frozen modules' behaviour
- Any new route
- Any network call

---

## 3. Step-by-step

| # | Step | Command / action | Gate |
|---|---|---|---|
| 1 | Install Python 3.11 | `winget install Python.Python.3.11` | `python --version` → 3.11.x |
| 2 | Create venv | `python -m venv .venv` | `.venv\Scripts\python.exe` exists |
| 3 | Install deps | `.venv\Scripts\python.exe -m pip install -r requirements.txt` | import smoke passes |
| 4 | Install pytest | `.venv\Scripts\python.exe -m pip install pytest` | `pytest --version` |
| 5 | **Snapshot DB** | copy `taxkernel_prod.db` → `backups/taxkernel_prod.pre-M0.db` | sizes equal, file readable |
| 6 | Run pytest | `.venv\Scripts\python.exe -m pytest -q` | 0 failures |
| 7 | Run unittest | `.venv\Scripts\python.exe -m unittest test_production test_ca_firm test_engine` | `OK` |
| 8 | Verify DB untouched | compare per-table row counts vs snapshot | identical |
| 9 | Boot smoke | `uvicorn main:app --host 127.0.0.1 --port 8010` on a temp DB copy | server listens |
| 10 | Route smoke | `/`, `/status`, `/ca`, `/capture`, `/summary`, `/api/ca/taxpayers`, `POST /invoice`, `GET /invoice/{id}/proof` | all HTTP 200 |
| 11 | Write evidence | `BASELINE.md` | versions, counts, smoke table |
| 12 | Commit | `chore(m0): establish green baseline` | clean tree |

---

## 4. Pre-known hazards

| Hazard | Why it matters | Handling |
|---|---|---|
| **`zeroconf` native DLL blocked** (Application Control policy) | `from main import app` fails → all pytest collection fails | Guard import with `MDNS_AVAILABLE`; disable `.pyd` files in the venv to use pure-Python fallbacks |
| **`test_engine.py` drift** | Written against older `database`/`tax_rules` signatures | Update the test only — never the frozen suites |
| **`clear_db()` wipes the live DB** | Every test run destroys ledger rows | Bind `test_engine` to a temp DB; add `TAXKERNEL_DB_PATH` override |
| **`taxkernel.db` is 0 bytes** | Tempting to "fix" it | Ignore it; assert every script targets `*_prod.db` |
| **No `git` on `PATH`** | Cannot commit from a plain shell | Use the GitHub Desktop bundled git |
| **`POST /invoice` has no `invoice_count`** | Stale expectation | Read `invoice_count` from `GET /status` |
| **mDNS needs LAN** | Advertises `taxkernel-pc.local` | Non-essential; smoke uses `127.0.0.1` |

---

## 5. Acceptance criteria

- [x] Python 3.11.9 in a repo-local `.venv`, deps installed
- [x] `pytest -q` → **22 passed**
- [x] `unittest` → **22 tests OK**
- [x] Pre-M0 DB snapshot exists; live DB row counts unchanged
- [x] Server boots; `/status` returns 200
- [x] Invoice proof route `GET /invoice/{id}/proof` returns 200
- [x] `/api/ca/taxpayers` returns 200
- [x] `/`, `/ca`, `/capture`, `/summary` all render
- [x] Every pre-existing failure documented with a root cause
- [x] No `intel/`, no schema change, no frozen file modified
- [x] `BASELINE.md` committed

---

## 6. Deliverables

| Artifact | Purpose |
|---|---|
| `BASELINE.md` | Versions, package list, row counts, test results, smoke matrix, triage |
| `backups/taxkernel_prod.pre-M0.db` | Pre-change snapshot (gitignored) |
| Test-isolation fixes | `test_engine.py` temp DB, `TAXKERNEL_DB_PATH` override |
| Import guard | App boots even when mDNS cannot load |

---

## 7. Exit → entry contract for M1

M0 hands M1 the following guarantees:

1. **A green suite to protect.** Any M1 change that breaks the 22 tests is a regression.
2. **A frozen cipher.** `crypto_vault.py` / `ssi_vault.py` are byte-identical to the
   pre-fork versions, so M1's keystore work is *purely additive* via subclasses.
3. **A known DB.** 86 KB, 15 tables, 1 user / 1 client / 2 FYs / 1 approval, and a
   verified snapshot to restore from if a migration goes wrong.
4. **A boot procedure.** `TAXKERNEL_DB_PATH` lets M1 test migrations against a temp copy
   without risking the ledger.

---

## 8. Rollback

| Failure | Rollback |
|---|---|
| Deps unusable | delete `.venv`, recreate |
| Suite red after triage | `git checkout -- test_engine.py` |
| DB damaged | restore `backups/taxkernel_prod.pre-M0.db` over `taxkernel_prod.db` |
| App will not boot | revert the `zeroconf` guard; run with mDNS disabled |
