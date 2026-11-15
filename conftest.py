"""Pytest session isolation.

Two frozen test suites (``test_production.py``) still do two things that are
unsafe on a developer machine:

* ``database.clear_db()`` — drops every table in whatever database is bound;
* ``CryptoVault()`` — recreates a plaintext key file when none exists.

Both files are frozen by the migration plan, so isolation is applied here
instead: the whole pytest session is bound to a throwaway database and
throwaway key paths before any test module is imported. The live ledger
(``taxkernel_prod.db``) and the OS keystore are never written by tests.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

_SESSION_DIR = Path(tempfile.mkdtemp(prefix="taxkernel-pytest-"))

# Must be set before `database` is imported by a test module.
os.environ["TAXKERNEL_DB_PATH"] = str(_SESSION_DIR / "taxkernel_pytest_prod.db")

import crypto_vault  # noqa: E402
import ssi_vault  # noqa: E402

crypto_vault.KEY_FILE = str(_SESSION_DIR / ".taxkernel_vault.key")
ssi_vault.KEY_FILE = str(_SESSION_DIR / ".taxkernel_did.key")
