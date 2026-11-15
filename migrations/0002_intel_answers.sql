-- Migration 0002: Add append-only intel_answers table for auditability and replayability.

CREATE TABLE IF NOT EXISTS intel_answers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL DEFAULT 1,
    taxpayer_id INTEGER,
    invoice_id INTEGER,
    query TEXT NOT NULL,
    envelope_json TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (id),
    FOREIGN KEY (taxpayer_id) REFERENCES taxpayers (id),
    FOREIGN KEY (invoice_id) REFERENCES invoices (id)
);

CREATE INDEX IF NOT EXISTS idx_intel_answers_user ON intel_answers(user_id);
CREATE INDEX IF NOT EXISTS idx_intel_answers_created ON intel_answers(created_at);
