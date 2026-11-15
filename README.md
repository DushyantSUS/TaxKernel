# TaxKernel

**A local-first operating system for Indian tax and compliance.**
Your invoices, ledgers, and filings stay on your machine — no cloud, no third-party reads.

TaxKernel pairs a **deterministic calculation core** (GST, TDS, transfer pricing, AIS
reconciliation, advance tax, forecasting) with an **intelligence layer** that explains
results in plain language. The engines own every number; the narrator only explains them.

> **Status:** All Milestones (**M0 through M9**) are complete, verified, and passing 93/93 tests with 100% strict mypy compliance on `intel/`.

---

## Why TaxKernel

| Problem | What TaxKernel does |
|---|---|
| Government AIS data doesn't match your books | Reconciles local invoices against AIS entries before you file |
| Wrong business/professional classification | Classifies activity and simulates a retroactive switch |
| GST/ITC leakage | Computes GSTR-3B / GSTR-9 and matches input tax credit |
| TDS & cross-border double taxation | §393 withholding rates, Form 16A, TP simulation, 3CEB, DTAA checks |
| Advance-tax cash-flow crunch | Taxes money received vs. money still owed |
| CA firms juggling many clients | Per-taxpayer isolated ledgers, bulk AIS, audit packages, notice tracker |

---

## Architecture at a glance

```
FastAPI edge hub (:8000)
   │
   ├── Deterministic engines   tax_rules · ais · gst · tds · tp · forecast · classifier · ca
   ├── Intelligence layer      intel/ — intent → orchestrator → narrator → envelope
   ├── Domain services         database · crypto_vault · ssi_vault · merkle_tree
   └── Storage                 SQLite taxkernel_prod.db (AES-256-GCM fields) · keyring/DPAPI
```

- **Live database:** `taxkernel_prod.db` (`taxkernel.db` is unused).
- **Crypto:** field-level AES-256-GCM; master key moving to OS keystore (`keyring`).
- **No network by default:** optional local LLM is gated behind `TAXKERNEL_LLM=1`.

Read the full design in [`ARCHITECTURE.md`](ARCHITECTURE.md); the execution plan is in
[`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md); requirements are in
[`TAXKERNEL_INTEL_MASTER_SPEC.md`](TAXKERNEL_INTEL_MASTER_SPEC.md).

---

## Quick start

**Requirements:** Windows, Python **3.11+**.

```powershell
# 1. From the repo root
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 2. Start the server
.\.venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# 3. Open the dashboard
#    http://localhost:8000
#    Presentation surface: http://localhost:8000/present
```

On first boot the app creates/uses `taxkernel_prod.db`, seeds a demo user/client, and
generates a pairing PIN.

Helper scripts: `run.ps1` (venv + deps + tests + server) and `load_all_data.ps1`
(loads 20 sample invoices while the server runs).

---

## Tests

The suites are standard-library `unittest`; `pytest` discovers them too.

```powershell
# unittest (original runner)
.\.venv\Scripts\python.exe -m unittest test_production.py test_ca_firm.py test_engine.py

# pytest (collects the unittest classes + new pytest-style tests)
.\.venv\Scripts\python.exe -m pytest -q
```

New intelligence-layer tests are pytest-style; existing suites are not rewritten.

---

## Project layout

```
main.py                 FastAPI app and 48 routes
database.py             SQLite schema + CRUD (transparent encryption)
crypto_vault.py         AES-256-GCM field encryption, pairing PIN
ssi_vault.py            did:key + Verifiable Credentials
merkle_tree.py          Tamper-evident invoice proofs
tax_rules.py            Thresholds, slabs, 44ADA, advance tax, accrual
ais_engine.py           AIS reconciliation
gst_engine.py           GSTR-3B / GSTR-9 / ITC matching
tds_engine.py           §393 rates, Form 16A
tp_engine.py            Transfer pricing, 3CEB, DTAA
forecast_engine.py      GST crossing, cash-flow, penalties, regime
classifier_engine.py    Business/professional classifier, defense brief
ca_engine.py            CA-firm bulk compliance
agent_engine.py         Legacy interactive agent (Tier-2 gated)
intel/                  Intelligence layer (planned, milestone-driven)
migrations/             Additive schema migrations (planned)
templates/              Jinja dashboards (dashboard, ca_dashboard, capture, summary)
test_*.py               unittest suites
```

---

## Dashboards

| URL | Purpose |
|---|---|
| `/` | Freelancer dashboard — ledger state, tax, forecasts |
| `/present` | Presentation pitch/demo — live engine snapshot, no DB access |
| `/ca` | CA-firm portal — taxpayer roster, compliance matrix, notices |
| `/capture` | Mobile-friendly invoice capture |
| `/summary` | Shareable summary (QR) |

---

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `TAXKERNEL_LLM` | `0` | Set to `1` to enable the optional local LLM (Tier 2) |
| `DB_PATH` | `taxkernel_prod.db` (`database.py:5`) | Live SQLite database |

The optional LLM runs on localhost only (Ollama / llama-cpp) with deterministic decoding
(`temperature=0`, fixed seed, `top_p=1`). Templates are always available as a fallback.

---

## Security & privacy

- **Local-first:** no cloud, no remote telemetry, no third-party access.
- **Encryption at rest:** AES-256-GCM for PII columns; invoice amounts remain plain for
  fast SQL aggregates.
- **Keys:** moving from plaintext `.taxkernel_vault.key` / `.taxkernel_did.key` to the Windows
  keystore (`keyring`/DPAPI) with HKDF per tenant.
- **Passwords:** device passwords moving from plaintext to **Argon2id**.
- **Integrity:** Merkle roots + approvals hash chain; invoices are append-only.
- **Network:** outbound calls off by default; mDNS is LAN-only.

> Do not commit `.taxkernel_vault.key`, `.taxkernel_did.key`, `.taxkernel_pairing.pin`, or
> `taxkernel_prod.db` to version control.

---

## Roadmap (Delivered & Verified)

| Milestone | Scope | Status |
|---|---|:---:|
| **M0** | Environment + green baseline (Python 3.11, `.venv`, tests) | ✅ Complete |
| **M1** | Keystore migration + Argon2id device passwords | ✅ Complete |
| **M2** | `intel/` skeleton (`Envelope`, confidence stub, mypy strict) | ✅ Complete |
| **M3** | Intent classifier + deterministic orchestrator | ✅ Complete |
| **M4** | Template narrator + guardrails + simulator | ✅ Complete |
| **M5** | Local RAG (SQLite FTS5 + BM25) with citation enforcement | ✅ Complete |
| **M6** | Confidence fusion + append-only answer log | ✅ Complete |
| **M7** | `/intel/*` API + dashboard progressive disclosure integration | ✅ Complete |
| **M8** | Self-audit, drift detection, DPDP retention | ✅ Complete |
| **M9** | Hardening, 93-test green matrix, Tier-2 LLM gate | ✅ Complete |

Detailed gates and risks: [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md).

---

## Contributing guardrails

These are locked for the intelligence-layer work:

- `database.py` schema changes **only** via `migrations/`.
- `crypto_vault.py` (key paths, cipher) and `ssi_vault.py` (key paths, DID) are frozen.
- `agent_engine.py` is Tier-2 only; `classifier_engine.py` semantics are frozen.
- Existing rows in `taxkernel_prod.db` are immutable.
- `test_production.py` and `test_ca_firm.py` must not be rewritten to pytest.
- `intel/` lives at repo root; never create a `taxkernel/` package.

---

## Documentation

| Doc | Contents |
|---|---|
| [`TAXKERNEL_INTEL_MASTER_SPEC.md`](TAXKERNEL_INTEL_MASTER_SPEC.md) | Approved requirements + locked decisions |
| [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) | Milestones, gates, risk register |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | System design, data flow, crypto, RAG, API |
| `ADAPTATION_REPORT.md` | Repo baseline analysis (historical) |

---

## License

Not specified in this repository. Add a license before distributing.
