# TaxKernel — Final Architecture

**Version:** 1.0
**Date:** 2026-11-15
**Companion docs:** `TAXKERNEL_INTEL_MASTER_SPEC.md` (requirements) · `IMPLEMENTATION_PLAN.md` (execution)

---

## 1. Purpose

TaxKernel is a **local-first** tax and compliance operating system for Indian freelancers,
small businesses, and CA firms. All financial data stays on the host. The system pairs a
**deterministic calculation core** with an optional **narrated intelligence layer**: the
engines own every number, the language model (when enabled) only explains them.

This document describes the final target architecture. It separates what **exists today**
from what is **planned** (the `intel/` layer and security hardening).

---

## 2. Design principles

| # | Principle | Consequence |
|---|---|---|
| B1 | **Deterministic core, narrated surface** | Math/law/reconciliation in code; phrasing in templates/LLM |
| B2 | **Every statement is traceable** | Each answer exposes citations, rules fired, raw engine output |
| B3 | **Calibrated confidence** | Signals fuse into 0–100 with high/medium/low/refuse bands |
| B4 | **Refusal is a feature** | Missing citation, numeric mismatch, or low confidence → structured refusal |
| B5 | **Progressive disclosure** | UI: summary → reasoning → raw evidence (Merkle hash, rule code, statute) |

No cloud. No chat avatar. No fabricated citations.

---

## 3. System context

```
                         ┌─────────────────────────────────────────┐
                         │            Operator (local)             │
                         │   Browser  ·  Paired phone  ·  Arduino  │
                         └───────────────┬─────────────────────────┘
                                         │ HTTP / WebSocket (LAN)
                         ┌───────────────▼─────────────────────────┐
                         │        FastAPI Edge Hub  (:8000)         │
                         │  Auth → Rate limit → Tenant ctx → routes │
                         └───────────────┬─────────────────────────┘
             ┌───────────────────────────┼───────────────────────────┐
             ▼                           ▼                           ▼
   ┌──────────────────┐      ┌──────────────────────┐      ┌──────────────────┐
   │ Deterministic    │      │ Intelligence Core    │      │ Duty/Compliance  │
   │ Engines          │◄────►│ intel/               │      │ UI (Jinja)       │
   │ (existing)       │      │ (orchestrator, RAG,  │      │ dashboard/ca/…   │
   │                  │      │  narrator, confidence)│     │                  │
   └────────┬─────────┘      └──────────┬───────────┘      └──────────────────┘
            │                           │
            ▼                           ▼
   ┌─────────────────────────────────────────────────────────────────────┐
   │ Storage: SQLite taxkernel_prod.db (field-level AES-256-GCM)             │
   │ Crypto: keyring/DPAPI master key + HKDF per tenant                  │
   │ RAG: SQLite FTS5 (+ optional small embeddings)                      │
   └─────────────────────────────────────────────────────────────────────┘
```

---

## 4. Layered view

```
L5  Presentation      templates/*.html (dashboard, ca_dashboard, capture, summary)
L4  API               main.py — 48 existing routes + /intel/* (planned)
L3  Intelligence      intel/{intent,orchestrator,narrator,confidence,rag,simulator,selfaudit}
L2  Deterministic     tax_rules, ais_engine, gst_engine, tds_engine, tp_engine,
                      forecast_engine, classifier_engine, ca_engine, agent_engine
L1  Domain services   database, crypto_vault, ssi_vault, merkle_tree
L0  Storage           SQLite taxkernel_prod.db · keyring/DPAPI · local corpus
```

Dependencies point **downward**: `intel/` calls L2/L1, never the reverse.

---

## 5. Component catalog

### 5.1 Existing (must not be replaced)

| Module | Responsibility | Key entry points |
|---|---|---|
| `main.py` | FastAPI app, auth, mDNS, WebSockets, 48 routes, templates | route handlers |
| `database.py` | Schema + CRUD, transparent encrypt/decrypt | `add_invoice`, `get_invoices`, `add_taxpayer`, … |
| `crypto_vault.py` | AES-256-GCM field encryption, pairing PIN, device tokens | `encrypt`, `decrypt`, `verify_pairing_pin` |
| `ssi_vault.py` | `did:key`, Verifiable Credential issue/verify | `issue_verifiable_credential`, `verify_credential` |
| `merkle_tree.py` | Tamper-evident invoice root | `MerkleTree(leaves).get_root()` |
| `tax_rules.py` | Thresholds, slabs, 44ADA, advance tax, accrual | `calculate_44ada_tax`, `get_upcoming_advance_tax` |
| `ais_engine.py` | AIS reconciliation, draft invoices, variance | `reconcile`, `generate_draft_invoices` |
| `gst_engine.py` | GSTR-3B / GSTR-9 / ITC matching | `calculate_gstr3b`, `reconcile_itc` |
| `tds_engine.py` | §393 rates, Form 16A | `verify_tds_rate`, `generate_form16a` |
| `tp_engine.py` | Transfer pricing, 3CEB, DTAA | `simulate_arms_length_range`, `check_dtaa_compliance` |
| `forecast_engine.py` | GST crossing, cash-flow, penalties, regime | `ForecastEngine` |
| `classifier_engine.py` | Business/professional classifier, defense brief | `classify_activity`, `generate_defense_brief` |
| `agent_engine.py` | Legacy interactive agent (Tier-2 gated) | `run_agentic_workflow` |
| `ca_engine.py` | CA-firm bulk AIS, advance tax, audit package | `bulk_ais_reconcile`, `generate_ca_audit_package` |

### 5.2 Planned — `intel/` (repo root)

| File | Responsibility |
|---|---|
| `intel/envelope.py` | `Envelope` dataclass + JSON serialization |
| `intel/intent.py` | Rules-first intent classifier (no LLM) |
| `intel/orchestrator.py` | Intent → engine(s) → facts |
| `intel/narrator.py` | Template Tier-1 narration + numeric guard |
| `intel/confidence.py` | Signal fusion → score + band |
| `intel/rag.py` | SQLite FTS5 + BM25 over local corpus |
| `intel/corpus/build.py` | Build-time indexer |
| `intel/simulator.py` | What-if sandbox over deterministic engines |
| `intel/selfaudit.py` | Nightly recompute + drift detection |
| `intel/keystore.py` | keyring/DPAPI master key + DID seed |
| `intel/vault.py` | Key-source subclasses (keeps `crypto_vault.py`/`ssi_vault.py` unchanged) |
| `intel/passwords.py` | Argon2id hash/verify for device passwords |
| `intel/templates/*.j2` | `ais_mismatch`, `regime_compare`, `refusal` |
| `intel/models/` | Ollama card / optional `.gguf` placeholder |

---

## 6. Request lifecycle (intelligence path)

```
User query
   │
   ▼
[intent.py] ── classify (rules-first) ──► intent + slots
   │
   ▼
[orchestrator.py] ── call deterministic engines ──► facts {numbers, raw}
   │
   ├──► [rag.py] ── resolve citations ──► citations[]      (must all resolve)
   │
   ├──► [confidence.py] ── fuse signals ──► score + band
   │
   ▼
[narrator.py] ── Tier 1 templates (default) / Tier 2 LLM (opt-in)
   │              numeric guard: every number must exist in facts
   ▼
Envelope {answer, citations, rules_fired, numbers, confidence, band,
          human_review_required, refusal_reason?, evidence_refs[]}
   │
   ▼
UI: summary → reasoning → raw evidence
```

**Invariant:** the LLM never computes. If a number is not in `facts`, the answer is
rejected and a refusal is returned.

---

## 7. Envelope contract

```json
{
  "query": "Why was invoice 12 flagged?",
  "answer": "Plain prose, <= 200 words.",
  "citations": [{"source": "ITA 2025", "section": "44ADA", "url": null}],
  "rules_fired": [{"engine": "tax_rules", "fn": "calculate_44ada_tax", "version": "1.0", "args_digest": "…"}],
  "numbers": [{"label": "Estimated tax", "value": 123456.0, "source_engine": "tax_rules"}],
  "confidence": 87,
  "band": "high",
  "human_review_required": false,
  "refusal_reason": null,
  "evidence_refs": [{"merkle_hash": "…", "invoice_id": 12}]
}
```

**Bands:** `high` (≥80), `medium` (50–79), `low` (<50), `refused` (guardrail triggered).
`human_review_required` is true when `band != "high"` or any citation is provisional.

---

## 8. Confidence model

| Signal | Source | Weight (initial) |
|---|---|---|
| AIS match quality | `ais_engine.reconcile` | 0.30 |
| Classifier certainty | `classifier_engine.classify_activity` | 0.25 |
| Forecast residual | `forecast_engine` | 0.15 |
| RAG hit quality (BM25 + coverage) | `intel/rag.py` | 0.20 |
| Data completeness (missing fields) | orchestrator | 0.10 |

`score = round(100 * Σ wᵢ·sᵢ)`. Weights live in one module and are unit-tested; they are
**not** tuned by the LLM.

---

## 9. Refusal taxonomy

| Code | Trigger | User-facing guidance |
|---|---|---|
| `NO_CITATION` | Cited section absent from corpus | Show what is missing; suggest uploading corpus |
| `NUMERIC_MISMATCH` | Narrated number ∉ `Envelope.numbers` | Re-run via template; hide LLM text |
| `LOW_CONFIDENCE` | `band == "low"` | Ask for more data |
| `OUT_OF_SCOPE` | Intent not in whitelist | List supported topics |
| `INSUFFICIENT_DATA` | Required engine inputs missing | Name the missing fields |

Every refusal is a valid `Envelope` with `band="refused"` and a non-null `refusal_reason`.

---

## 10. RAG & corpus

- **Store:** SQLite **FTS5** table in `taxkernel_prod.db` (or a sibling index DB).
- **Retrieval:** BM25 (pure Python `rank_bm25` or FTS5 `bm25()`), top-k with score.
- **Optional embeddings:** small static vectors (e.g. `model2vec`, ~30 MB) scored with
  `numpy`; **no** torch/faiss/chromadb in the base install.
- **Corpus:** `intel/corpus/{ita_2025,cbdt_circulars,gst_rates,itat_precedents}/`.
- **Rule:** a citation is only emitted if its section resolves; otherwise refuse.

---

## 11. LLM tiers

| Tier | Runtime | Default | Determinism |
|---|---|---|---|
| **Tier 0** | Pure Jinja templates | ✅ always | Fully deterministic |
| **Tier 1** | Template selection + post-processing | ✅ | Fully deterministic |
| **Tier 2** | Ollama / llama-cpp (localhost) | ⛔ off (`TAXKERNEL_LLM=1`) | `temperature=0`, fixed seed, `top_p=1` |

Tier 2 is optional, localhost-only, and never required for correctness. `agent_engine.py`
is legacy-interactive and also gated by `TAXKERNEL_LLM=1` (D3).

---

## 12. Data architecture

### 12.1 Existing tables (16, in `taxkernel_prod.db`)

`users`, `clients`, `financial_years`, `invoices`, `approvals`, `devices`,
`merkle_roots`, `ais_entries`, `purchases`, `gstr2b_entries`, `tds_records`,
`cross_border_tx`, `taxpayers`, `staff_members`, `notice_tracker`, `sqlite_sequence`.

Encrypted columns are marked in `database.py`; `invoices.amount` is intentionally plain
for SQL aggregates.

### 12.2 Additive changes (only via `migrations/`)

- `devices.device_password_hash TEXT` — Argon2id (M1).
- `intel_answers(id, user_id, taxpayer_id, invoice_id, query, envelope_json, created_at)`
  — append-only answer log (M6).
- Optional `invoices` evidence columns (`intel_envelope_id`, `intel_band`,
  `rule_bundle_version`, `evidence_hash`) — nullable, never backfilled.
- Optional `taxpayers` columns (`tenant_salt`, `keystore_ref`, `dpdp_consent_at`,
  `retention_until`, `risk_score`).

**Rules:** no `UPDATE`/`DELETE` of existing invoices; migrations idempotent; backup before
DDL; every script targets `taxkernel_prod.db`.

---

## 13. Crypto & key management

| Concern | Today | Target |
|---|---|---|
| Field cipher | AES-256-GCM, nonce‖ciphertext, base64 (`crypto_vault.py`) | unchanged |
| Master key | `.taxkernel_vault.key` on disk | **keyring** (Windows DPAPI), service `TaxKernel` |
| Per-tenant keys | none (single key) | `HKDF-SHA256(master, tenant_salt)` |
| DID key | `.taxkernel_did.key` PEM on disk | encrypted under master / keystore seed |
| Pairing PIN | `.taxkernel_pairing.pin` plaintext file | ephemeral, keystore-backed |
| Device passwords | plaintext `devices.device_password` | **Argon2id** (`device_password_hash`) |

Key source is injected via `intel/vault.py` subclasses so `crypto_vault.py` and
`ssi_vault.py` remain byte-identical (DO-NOT-MODIFY).

---

## 14. Security, privacy, compliance

- **Local-first:** no cloud, no external DB, no third-party reads.
- **Network posture:** outbound network disabled by default; mDNS is LAN-only; optional
  LLM is localhost-only. Remove/replace the `8.8.8.8` probe during hardening.
- **Auth:** pairing PIN → device token; device password verified with Argon2id.
- **Tenancy:** per-taxpayer ledger (`taxpayers.user_id → users`); AIS scoped by
  `taxpayer_id`.
- **Integrity:** Merkle roots + approvals hash chain; invoices append-only.
- **DPDP Act 2023:** consent timestamp, retention marker, backup/restore story.
- **Threat model:** LAN surface (mDNS + :8000) is primary; add rate limiting, bind to
  loopback by default, document pairing.

---

## 15. API surface

### 15.1 Existing (48 routes, unchanged)

Grouped: pairing/auth (4), invoices/ledger (10), compliance/ITR/GST/TDS/TP (18),
CA suite (7), UI/SSI/QR (5), reset (1). See `main.py` or `ADAPTATION_REPORT.md §1.3`.

### 15.2 Planned additions (append-only)

| Method | Path | Purpose |
|---|---|---|
| POST | `/intel/ask` | Query → `Envelope` |
| POST | `/intel/simulate` | What-if sandbox |
| GET | `/intel/health` | Corpus/model/keystore status |
| GET | `/intel/answer/{id}` | Replay stored envelope |

---

## 16. Runtime & deployment

- **Local:** `python -m venv .venv`, `pip install -r requirements.txt`, `uvicorn main:app`.
- **Port:** 8000 (LAN, mDNS `taxkernel-pc.local`).
- **Optional container:** `Dockerfile` (python:3.11-slim) + `docker-compose.yml` exist;
  Redis service is legacy and not required by the current code path.
- **Offline:** all engines and templates ship in-repo; models are optional.

---

## 17. Module map

```
TaxKernel/
├── main.py                  # FastAPI, 48 routes
├── database.py              # schema + CRUD
├── crypto_vault.py          # AES-GCM (frozen)
├── ssi_vault.py             # DID/VC (frozen)
├── merkle_tree.py
├── tax_rules.py
├── ais_engine.py
├── gst_engine.py
├── tds_engine.py
├── tp_engine.py
├── forecast_engine.py
├── classifier_engine.py     # frozen semantics
├── ca_engine.py
├── agent_engine.py          # Tier-2 gated
├── intel/                   # NEW (root, never taxkernel/)
│   ├── envelope.py
│   ├── intent.py
│   ├── orchestrator.py
│   ├── narrator.py
│   ├── confidence.py
│   ├── rag.py
│   ├── simulator.py
│   ├── selfaudit.py
│   ├── keystore.py
│   ├── vault.py
│   ├── passwords.py
│   ├── corpus/
│   ├── templates/
│   └── models/
├── migrations/              # NEW (schema changes only here)
├── templates/               # existing Jinja UI
├── test_production.py       # unittest (frozen)
├── test_ca_firm.py          # unittest (frozen)
├── test_engine.py           # unittest
├── TAXKERNEL_INTEL_MASTER_SPEC.md
├── IMPLEMENTATION_PLAN.md
├── ARCHITECTURE.md
└── README.md
```

---

## 18. Architecture decisions (ADR summary)

| ID | Decision | Rationale |
|---|---|---|
| Q1 | Single master spec | One source of truth |
| Q2 | Python 3.11 + green baseline first | No code on an unknown baseline |
| Q3 | `intel/` at root | Avoid risky package migration |
| Q4 | `keyring` (DPAPI) | OS-native secret storage, no new C++ |
| Q5 | Argon2id device-only (M1) | Smallest safe security win |
| D1 | `taxkernel_prod.db` only | Prevent split-brain data |
| D2 | unittest + pytest mixed | Preserve existing suites |
| D3 | `TAXKERNEL_LLM=1` gate | Keep default offline/deterministic |
| D4 | Route smoke per milestone | Catch boot/UI regressions |

---

## 19. Non-goals

- Cloud sync, multi-user SaaS, remote telemetry.
- LLM arithmetic or free-form legal advice.
- Replacing the deterministic engines with generated code.
- Migrating existing modules into a `taxkernel/` package.

---

## 20. Failure modes & fallbacks

| Failure | Behaviour |
|---|---|
| No LLM/model | Tier-0/1 templates (always available) |
| Keyring unavailable | Documented DPAPI fallback; warn loudly |
| RAG index empty | Refuse with `NO_CITATION`; suggest corpus build |
| Engine exception | Structured error envelope; no fabricated number |
| DB migration conflict | Abort, restore backup, report |
| Corrupt DB | Restore from `backups/`; integrity check first |
