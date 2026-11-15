# TaxKernel — Intelligence Layer & Hardening — Master Spec
Version: 1.0 (final, consolidated)
Replaces: IMPLEMENTATION_PLAN.md + APPENDIX_INTEL_SPEC.md
Target environment: Windows host, flat repo at C:\Users\works\OneDrive\Desktop\TaxKernel
Live DB: taxkernel_prod.db (see §1)
Status: APPROVED for execution, milestone-by-milestone.

---

## §0 — How to use this file

1. Save this file to repo root as TAXKERNEL_INTEL_MASTER_SPEC.md.
2. Delete IMPLEMENTATION_PLAN.md and APPENDIX_INTEL_SPEC.md (superseded).
3. Commit: `git commit -am "chore: add consolidated intel master spec"`.
4. Paste §2 (Master Prompt) into OpenCode.
5. The agent's first output MUST be PLAN_M0.md. If it produces code
   instead, reject and re-prompt with §12 Step 3 only.

Every milestone prompt after M0 ends with:
"Repeat the DO-NOT-MODIFY list from §1.3 verbatim. Do not proceed past
this milestone until I approve."

---

## §1 — Repo facts (ground truth, do not re-derive)

### 1.1 Environment
- 17 *.py files, all flat at repo root. No taxkernel/ package.
- No Python installed (Microsoft Store stub). Must install 3.11 via winget.
- No .venv, no pytest, no sqlite3 CLI.
- Tests are `unittest.TestCase` in test_production.py, test_ca_firm.py.
- main.py has 48 routes. Dashboards: templates/dashboard.html,
  templates/ca_dashboard.html.

### 1.2 Data
- taxkernel.db is 0 bytes (ignore it).
- **Live DB: taxkernel_prod.db** — defined at database.py:5. 16 tables.
- Keys on disk: .taxkernel_vault.key, .taxkernel_did.key (plaintext, repo root).
- devices.device_password is stored plaintext (to be migrated to argon2id).

### 1.3 DO NOT MODIFY (repeat in every milestone prompt)
- database.py schema, EXCEPT via new files in migrations/
- crypto_vault.py (key paths, cipher)
- ssi_vault.py (key paths, DID)
- agent_engine.py — Tier-2 gate only (see D3 in §1.5)
- classifier_engine.py (income classifier — distinct from intel/intent.py)
- Existing rows in taxkernel_prod.db
- Existing tests test_production.py, test_ca_firm.py (do not rewrite to pytest)

### 1.4 Package layout decision
- intel/ at repo root, NOT taxkernel/intel/.
- mypy target: `mypy intel/ --strict`.
- Imports: `from intel.envelope import Envelope` (never `from taxkernel.intel`).

### 1.5 Decisions log (locked)
| ID | Decision |
|---|---|
| Q1 | Spec = this file. IMPLEMENTATION_PLAN.md and APPENDIX_INTEL_SPEC.md are deleted. |
| Q2 | Install Python 3.11 + .venv before M0. Baseline must be GREEN before any code is written. |
| Q3 | intel/ at root. No taxkernel/ directory is ever created. |
| Q4 | Use `keyring` package (Windows backend = DPAPI). Fall back to direct DPAPI only on documented keyring failure. |
| Q5 | Argon2id applies to device passwords ONLY in M1. Per-taxpayer logins deferred. |
| D1 | Live DB is taxkernel_prod.db (database.py:5). Every script, migration, backup, self-audit targets this file. Scripts opening taxkernel.db are bugs. |
| D2 | Tests remain unittest. pytest auto-discovers them. New golden tests are pytest-style. Mixed is fine. |
| D3 | agent_engine.py's LLM HTTP calls are gated behind TAXKERNEL_LLM=1 (default OFF), matching intel/narrator Tier 2. agent_engine is legacy-interactive; intel/ is the compliant path. |
| D4 | After every milestone: start server, hit /status + /invoice GET + /api/ca/taxpayers. Confirm boot + dashboards. pytest alone is insufficient. |

---

## §2 — MASTER PROMPT (paste into OpenCode) this is the final implementation plan to code
