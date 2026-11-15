"""Idempotent schema migration runner.

Milestone M1 onward, ``database.py`` keeps its schema frozen and every change
lands here as an additive SQL file. The runner:

1. refuses to run against anything that is not a ``*_prod.db`` database
   (guards against the 0-byte ``taxkernel.db`` trap);
2. snapshots the database into ``backups/`` before the first DDL of a run;
3. records applied versions in ``schema_migrations`` and skips them on re-run;
4. backfills device passwords to Argon2id and clears the plaintext column.

Usage
-----
    python migrations/run.py --dry-run
    python migrations/run.py
    python migrations/run.py --db path/to/taxkernel_test_prod.db

Environment: ``TAXKERNEL_DB_PATH`` overrides the default database path.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import os
import shutil
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = Path(__file__).resolve().parent
BACKUP_DIR = REPO_ROOT / "backups"

# Running `python migrations/run.py` puts the migrations directory on sys.path,
# not the repo root, so `import intel` would fail. Add the root explicitly.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Mirrors database.DB_PATH's default without importing database.py (importing
# it constructs a CryptoVault and may create/read key material as a side
# effect, which a migration runner must not do).
DEFAULT_DB_PATH = REPO_ROOT / "taxkernel_prod.db"

REGISTRY = "schema_migrations"


# --------------------------------------------------------------------------- #
# Paths and safety
# --------------------------------------------------------------------------- #

def resolve_db_path(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    env = os.environ.get("TAXKERNEL_DB_PATH")
    if env:
        return Path(env).expanduser().resolve()
    return DEFAULT_DB_PATH.resolve()


def assert_prod_database(path: Path) -> None:
    """Refuse to touch anything that is not an explicitly production-named DB."""
    if not path.name.endswith("_prod.db"):
        raise SystemExit(
            f"refusing to migrate {path.name!r}: target must end with '_prod.db' "
            "(the 0-byte taxkernel.db must never be used)"
        )
    if not path.exists():
        raise SystemExit(f"database not found: {path}")
    if path.stat().st_size == 0:
        raise SystemExit(f"database is empty (0 bytes): {path}")


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def integrity_check(conn: sqlite3.Connection) -> str:
    row = conn.execute("PRAGMA integrity_check").fetchone()
    return str(row[0]) if row else "unknown"


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #

def ensure_registry(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {REGISTRY} (
            version TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL,
            checksum TEXT
        )
        """
    )
    conn.commit()


def registry_exists(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (REGISTRY,)
    ).fetchone()
    return row is not None


def applied_versions(conn: sqlite3.Connection, *, create: bool = False) -> set[str]:
    """Applied migration versions.

    ``create=False`` keeps dry-runs read-only: it reports an empty set instead
    of creating the registry table, so ``--dry-run`` cannot alter the file.
    """
    if not registry_exists(conn):
        if not create:
            return set()
        ensure_registry(conn)
    return {str(r["version"]) for r in conn.execute(f"SELECT version FROM {REGISTRY}")}


# --------------------------------------------------------------------------- #
# Discovery / application
# --------------------------------------------------------------------------- #

def discover_migrations() -> list[Path]:
    return sorted(p for p in MIGRATIONS_DIR.glob("*.sql") if p.is_file())


def backup_before(path: Path, version: str) -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    target = BACKUP_DIR / f"{path.stem}.pre-{version}-{stamp}.db"
    shutil.copy2(path, target)
    return target


def apply_migration(conn: sqlite3.Connection, path: Path, *, dry_run: bool) -> None:
    sql = path.read_text(encoding="utf-8")
    version = path.stem
    if dry_run:
        print(f"  [dry-run] would apply {version}")
        return
    try:
        conn.executescript(sql)
        conn.execute(
            f"INSERT OR REPLACE INTO {REGISTRY} (version, applied_at) VALUES (?, ?)",
            (version, _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")),
        )
        conn.commit()
    except sqlite3.Error:
        conn.rollback()
        raise


# --------------------------------------------------------------------------- #
# Password backfill (M1)
# --------------------------------------------------------------------------- #

def backfill_device_passwords(conn: sqlite3.Connection, *, dry_run: bool = False) -> int:
    """Hash legacy plaintext device passwords and null the plaintext column.

    Idempotent: rows that already have a hash are skipped, so re-running is a
    no-op. Returns the number of rows that were (or would be) upgraded.
    """
    from intel.passwords import hash_password, is_hash

    columns = {str(r["name"]) for r in conn.execute("PRAGMA table_info(devices)")}
    if "device_password_hash" not in columns:
        print("  device_password_hash column missing; skipping backfill")
        return 0

    rows = list(
        conn.execute(
            "SELECT id, device_password, device_password_hash FROM devices"
        )
    )
    upgraded = 0
    for row in rows:
        dev_id = int(row["id"])
        plaintext = row["device_password"]
        existing_hash = row["device_password_hash"]
        if existing_hash or not plaintext:
            continue
        stored = plaintext if is_hash(plaintext) else hash_password(str(plaintext))
        if dry_run:
            upgraded += 1
            continue
        conn.execute(
            "UPDATE devices SET device_password_hash = ?, device_password = NULL WHERE id = ?",
            (stored, dev_id),
        )
        upgraded += 1

    if not dry_run:
        conn.commit()
    return upgraded


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

def ensure_schema(db_path: Path) -> list[str]:
    """Apply pending migrations quietly and return the versions applied.

    Used at application startup so a fresh machine (or a pre-M1 database)
    never runs against a stale schema. Never raises for a missing/empty file:
    callers bootstrap the schema first.
    """
    if not db_path.exists() or db_path.stat().st_size == 0:
        return []
    conn = connect(db_path)
    try:
        ensure_registry(conn)
        done = applied_versions(conn, create=True)
        pending = [p for p in discover_migrations() if p.stem not in done]
        if not pending:
            return []
        backup_before(db_path, pending[0].stem)
        for path in pending:
            apply_migration(conn, path, dry_run=False)
        backfill_device_passwords(conn)
        return [p.stem for p in pending]
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply TaxKernel SQL migrations.")
    parser.add_argument("--db", help="explicit database path (must end with _prod.db)")
    parser.add_argument("--dry-run", action="store_true", help="report without writing")
    parser.add_argument(
        "--skip-backfill", action="store_true", help="skip device password backfill"
    )
    args = parser.parse_args(argv)

    db_path = resolve_db_path(args.db)
    assert_prod_database(db_path)

    print(f"database : {db_path}")
    print(f"size     : {db_path.stat().st_size} bytes")

    conn = connect(db_path)
    try:
        pre = integrity_check(conn)
        print(f"integrity: {pre}")
        if pre != "ok":
            raise SystemExit("aborting: database failed PRAGMA integrity_check before migration")

        if not args.dry_run:
            ensure_registry(conn)
        done = applied_versions(conn, create=not args.dry_run)
        pending = [p for p in discover_migrations() if p.stem not in done]

        print(f"applied  : {len(done)}  pending: {len(pending)}")
        if not pending and args.skip_backfill:
            print("nothing to do")
            return 0

        if pending and not args.dry_run:
            backup = backup_before(db_path, pending[0].stem)
            print(f"backup   : {backup}")

        for path in pending:
            print(f"applying : {path.stem}")
            apply_migration(conn, path, dry_run=args.dry_run)

        if not args.skip_backfill:
            upgraded = backfill_device_passwords(conn, dry_run=args.dry_run)
            verb = "would upgrade" if args.dry_run else "upgraded"
            print(f"passwords: {verb} {upgraded} device row(s)")

        if not args.dry_run:
            post = integrity_check(conn)
            print(f"integrity: {post}")
            if post != "ok":
                raise SystemExit("database failed integrity_check after migration")
        print("done")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
