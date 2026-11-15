"""M1 security tests: Argon2id device passwords + OS keystore key custody.

pytest-style on purpose: only new intelligence-layer tests use pytest
(IMPLEMENTATION_PLAN.md decision D2). The legacy suites stay `unittest`.

These tests never touch the live database or the real keystore: they bind
`database.DB_PATH` to a temp file and swap `keyring` for an in-memory backend.
"""

from __future__ import annotations

import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Any

import keyring
import pytest
from keyring.backend import KeyringBackend

import database
from intel import keystore, passwords
from intel.vault import KeystoreCryptoVault, build_crypto_vault, build_ssi_vault

REPO_ROOT = Path(__file__).resolve().parent


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

class MemoryKeyring(KeyringBackend):
    """In-memory stand-in for the OS keystore."""

    priority = 1  # type: ignore[assignment]

    def __init__(self) -> None:
        self.store: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.store.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.store[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        self.store.pop((service, username), None)


class BrokenKeyring(MemoryKeyring):
    """Simulates a locked/unavailable keystore."""

    def get_password(self, service: str, username: str) -> str | None:
        raise RuntimeError("keystore is locked")

    def set_password(self, service: str, username: str, password: str) -> None:
        raise RuntimeError("keystore is locked")


@pytest.fixture()
def memory_keyring() -> Any:
    previous = keyring.get_keyring()
    backend = MemoryKeyring()
    keyring.set_keyring(backend)
    try:
        yield backend
    finally:
        keyring.set_keyring(previous)


@pytest.fixture()
def temp_disk_keys(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect *all* key paths into tmp so tests can never touch the repo keys."""
    import crypto_vault
    import ssi_vault

    vault_key = tmp_path / ".taxkernel_vault.key"
    did_key = tmp_path / ".taxkernel_did.key"
    monkeypatch.setattr(keystore, "VAULT_KEY_FILE", vault_key)
    monkeypatch.setattr(keystore, "DID_KEY_FILE", did_key)
    monkeypatch.setattr(crypto_vault, "KEY_FILE", str(vault_key))
    monkeypatch.setattr(ssi_vault, "KEY_FILE", str(did_key))
    return tmp_path


# --------------------------------------------------------------------------- #
# Argon2id
# --------------------------------------------------------------------------- #

def test_hash_is_argon2id_phc() -> None:
    digest = passwords.hash_password("correct horse battery staple")
    assert digest.startswith("$argon2id$")
    assert f"m={passwords.MEMORY_COST}" in digest
    assert f"t={passwords.TIME_COST}" in digest
    assert f"p={passwords.PARALLELISM}" in digest
    assert passwords.is_hash(digest) is True


def test_hash_is_salted() -> None:
    first = passwords.hash_password("same-password")
    second = passwords.hash_password("same-password")
    assert first != second
    assert passwords.verify_password(first, "same-password")
    assert passwords.verify_password(second, "same-password")


def test_verify_rejects_wrong_password() -> None:
    digest = passwords.hash_password("s3cret-device-pin")
    assert passwords.verify_password(digest, "s3cret-device-pin") is True
    assert passwords.verify_password(digest, "s3cret-device-pi") is False
    assert passwords.verify_password(digest, "") is False


def test_empty_password_is_rejected_not_hashed() -> None:
    with pytest.raises(passwords.WeakPasswordError):
        passwords.hash_password("")
    with pytest.raises(passwords.WeakPasswordError):
        passwords.hash_password("   ")


def test_verify_is_total_for_garbage() -> None:
    assert passwords.verify_password(None, "x") is False
    assert passwords.verify_password("not-a-hash", "") is False
    # A malformed PHC string must not raise.
    assert passwords.verify_password("$argon2id$broken", "x") is False


def test_needs_rehash() -> None:
    digest = passwords.hash_password("rotate-me")
    assert passwords.needs_rehash(digest) is False
    assert passwords.needs_rehash(None) is True
    assert passwords.needs_rehash("plaintext") is True


def test_legacy_plaintext_still_verifies() -> None:
    # One-release compatibility: rows written before M1 hold plaintext.
    assert passwords.verify_password("legacy-pass", "legacy-pass") is True
    assert passwords.verify_password("legacy-pass", "nope") is False


def test_hash_wins_over_plaintext() -> None:
    digest = passwords.hash_password("new-pass")
    assert passwords.verify_device_credentials("new-pass", digest, "new-pass") is True
    # The plaintext column must not be able to authenticate anything else.
    assert passwords.verify_device_credentials("decoy", digest, "decoy") is False


# --------------------------------------------------------------------------- #
# Keystore
# --------------------------------------------------------------------------- #

def test_master_key_is_created_and_stable(memory_keyring: MemoryKeyring, temp_disk_keys: Path) -> None:
    first = keystore.get_master_key()
    second = keystore.get_master_key()
    assert len(first) == 32
    assert first == second
    assert (keystore.SERVICE, keystore.MASTER_KEY_USER) in memory_keyring.store


def test_master_key_is_migrated_from_disk(memory_keyring: MemoryKeyring, temp_disk_keys: Path) -> None:
    disk_key = b"k" * 32
    keystore.VAULT_KEY_FILE.write_bytes(disk_key)

    got = keystore.get_master_key()
    assert got == disk_key, "existing ciphertext would no longer decrypt"
    assert keystore.status()["master_key"] == "present"


def test_migrate_from_disk_removes_files(memory_keyring: MemoryKeyring, temp_disk_keys: Path) -> None:
    keystore.VAULT_KEY_FILE.write_bytes(b"m" * 32)
    keystore.DID_KEY_FILE.write_bytes(b"-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----\n")

    result = keystore.migrate_from_disk(delete_disk=True)
    assert result == {"master_key": "migrated", "did_key": "migrated"}
    assert not keystore.VAULT_KEY_FILE.exists()
    assert not keystore.DID_KEY_FILE.exists()
    assert keystore.get_master_key() == b"m" * 32


def test_migrate_is_idempotent(memory_keyring: MemoryKeyring, temp_disk_keys: Path) -> None:
    keystore.VAULT_KEY_FILE.write_bytes(b"z" * 32)
    assert keystore.migrate_from_disk()["master_key"] == "migrated"
    assert keystore.migrate_from_disk()["master_key"] == "absent"


def test_disk_fallback_warns_when_keystore_is_broken(temp_disk_keys: Path) -> None:
    previous = keyring.get_keyring()
    keyring.set_keyring(BrokenKeyring())
    try:
        keystore.VAULT_KEY_FILE.write_bytes(b"f" * 32)
        assert keystore.get_master_key(allow_disk_fallback=True) == b"f" * 32

        keystore.VAULT_KEY_FILE.unlink()
        with pytest.raises(keystore.KeystoreUnavailable):
            keystore.get_master_key(allow_disk_fallback=False)
        with pytest.raises(keystore.KeystoreUnavailable):
            keystore.get_master_key(allow_disk_fallback=True)  # nothing to fall back to
    finally:
        keyring.set_keyring(previous)


def test_invalid_key_length_is_rejected(memory_keyring: MemoryKeyring, temp_disk_keys: Path) -> None:
    keystore.VAULT_KEY_FILE.write_bytes(b"short")
    with pytest.raises(keystore.KeystoreUnavailable):
        keystore.get_master_key()


# --------------------------------------------------------------------------- #
# Vaults
# --------------------------------------------------------------------------- #

def test_keystore_crypto_vault_round_trip(memory_keyring: MemoryKeyring, temp_disk_keys: Path) -> None:
    vault = KeystoreCryptoVault()
    payload = "INV-42|Acme Pvt Ltd|125000.00"
    sealed = vault.encrypt(payload)
    assert sealed != payload
    assert vault.decrypt(sealed) == payload
    assert KeystoreCryptoVault().decrypt(sealed) == payload
    # Ciphertext must be bound to the vault key.
    assert vault.decrypt(sealed[:-4] + "AAAA") != payload


def test_build_vaults_fall_back_without_keystore(temp_disk_keys: Path) -> None:
    previous = keyring.get_keyring()
    keyring.set_keyring(BrokenKeyring())
    try:
        vault = build_crypto_vault(allow_disk_fallback=True)
        sealed = vault.encrypt("fallback")
        assert vault.decrypt(sealed) == "fallback"
        assert keystore.VAULT_KEY_FILE.exists(), "fallback must persist a usable key"
    finally:
        keyring.set_keyring(previous)


def test_ssi_did_is_stable_across_keystore_migration(memory_keyring: MemoryKeyring, temp_disk_keys: Path) -> None:
    import ssi_vault

    legacy_did = ssi_vault.SSIVault().did
    keystore.migrate_from_disk(delete_disk=True)
    assert build_ssi_vault().did == legacy_did


def test_ssi_credentials_verify(memory_keyring: MemoryKeyring, temp_disk_keys: Path) -> None:
    vault = build_ssi_vault()
    credential = vault.issue_verifiable_credential(
        freelancer_name="Test",
        gst_status="UNDER_THRESHOLD",
        total_turnover=1000.0,
        last_hash="GENESIS",
    )
    assert vault.verify_credential(credential) is True
    credential["credentialSubject"]["gstStatus"] = "CROSS_LIMIT"
    assert vault.verify_credential(credential) is False


# --------------------------------------------------------------------------- #
# database.py integration (device credentials)
# --------------------------------------------------------------------------- #

@pytest.fixture()
def temp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from migrations import run as migration_runner

    db_path = tmp_path / "taxkernel_testsecrets_prod.db"
    monkeypatch.setattr(database, "DB_PATH", str(db_path))
    monkeypatch.setattr(migration_runner, "BACKUP_DIR", tmp_path / "backups")
    database.init_db()
    # M1 adds devices.device_password_hash; apply it exactly as production does.
    assert migration_runner.main(["--db", str(db_path), "--skip-backfill"]) == 0
    return db_path


def test_add_device_stores_only_a_hash(temp_db: Path) -> None:
    database.add_device("Phone", "token-hash", None, "device-pass-123")
    conn = sqlite3.connect(temp_db)
    row = conn.execute(
        "SELECT device_password, device_password_hash FROM devices WHERE device_token = ?",
        ("token-hash",),
    ).fetchone()
    conn.close()
    assert row is not None
    plaintext, digest = row
    assert plaintext is None, "plaintext password must not be stored"
    assert digest.startswith("$argon2id$")


def test_unlock_verifies_hash(temp_db: Path) -> None:
    database.add_device("Phone", "token-unlock", None, "device-pass-123")
    assert database.verify_device_password("token-unlock", "device-pass-123") is True
    assert database.verify_device_password("token-unlock", "wrong") is False
    assert database.verify_device_password("unknown-token", "x") is None


def test_literal_fallback_password_is_gone(temp_db: Path) -> None:
    conn = sqlite3.connect(temp_db)
    conn.execute(
        "INSERT INTO devices (device_name, device_token) VALUES ('Legacy', 'token-legacy')"
    )
    conn.commit()
    conn.close()
    # Pre-M1 the literal "taxkernel" unlocked a device with no password.
    assert database.verify_device_password("token-legacy", "taxkernel") is None
    assert database.verify_device_password("token-legacy", "") is None


def test_legacy_plaintext_row_still_unlocks_once(temp_db: Path) -> None:
    conn = sqlite3.connect(temp_db)
    conn.execute(
        "INSERT INTO devices (device_name, device_token, device_password) VALUES ('Legacy', 'token-plain', 'old-pass')"
    )
    conn.commit()
    conn.close()
    assert database.verify_device_password("token-plain", "old-pass") is True
    assert database.verify_device_password("token-plain", "wrong") is False


def test_new_device_is_hashed_even_before_migration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An unmigrated DB must still never receive a plaintext password."""
    db_path = tmp_path / "taxkernel_legacy_prod.db"
    monkeypatch.setattr(database, "DB_PATH", str(db_path))
    database.init_db()  # frozen schema: no device_password_hash column

    database.add_device("Phone", "token-unmigrated", None, "pass-123456")

    conn = sqlite3.connect(db_path)
    stored = conn.execute(
        "SELECT device_password FROM devices WHERE device_token = 'token-unmigrated'"
    ).fetchone()[0]
    conn.close()
    assert stored.startswith("$argon2id$"), "plaintext password leaked into an unmigrated DB"
    assert database.verify_device_password("token-unmigrated", "pass-123456") is True


# --------------------------------------------------------------------------- #
# Migration runner
# --------------------------------------------------------------------------- #

@pytest.fixture()
def runner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    from migrations import run as migration_runner

    # Never write test backups into the repo's backups/ directory.
    monkeypatch.setattr(migration_runner, "BACKUP_DIR", tmp_path / "backups")
    return migration_runner


def _bare_devices_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE devices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_name TEXT NOT NULL,
            device_token TEXT UNIQUE NOT NULL,
            public_key TEXT,
            device_password TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        "INSERT INTO devices (device_name, device_token, device_password) VALUES ('Old', 'tok-old', 'legacy-pass')"
    )
    conn.commit()
    conn.close()


def test_migration_adds_column_and_backfills(runner: Any, tmp_path: Path) -> None:
    db_path = tmp_path / "taxkernel_mig_prod.db"
    _bare_devices_db(db_path)

    assert runner.main(["--db", str(db_path)]) == 0

    conn = sqlite3.connect(db_path)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(devices)")}
    assert "device_password_hash" in columns
    versions = list(conn.execute("SELECT version FROM schema_migrations"))
    assert versions == [("0001_device_password_hash",)]
    plaintext, digest = conn.execute(
        "SELECT device_password, device_password_hash FROM devices WHERE device_token = 'tok-old'"
    ).fetchone()
    conn.close()
    assert plaintext is None
    assert digest.startswith("$argon2id$")
    assert passwords.verify_password(digest, "legacy-pass")


def test_migration_is_idempotent(runner: Any, tmp_path: Path) -> None:
    db_path = tmp_path / "taxkernel_mig2_prod.db"
    _bare_devices_db(db_path)

    assert runner.main(["--db", str(db_path)]) == 0
    assert runner.main(["--db", str(db_path)]) == 0  # must not raise


def test_migration_refuses_non_prod_and_empty_databases(runner: Any, tmp_path: Path) -> None:
    stray = tmp_path / "taxkernel.db"
    stray.write_bytes(b"")
    with pytest.raises(SystemExit):
        runner.main(["--db", str(stray)])

    empty_prod = tmp_path / "taxkernel_empty_prod.db"
    empty_prod.write_bytes(b"")
    with pytest.raises(SystemExit):
        runner.main(["--db", str(empty_prod)])


def test_migration_dry_run_changes_nothing(runner: Any, tmp_path: Path) -> None:
    db_path = tmp_path / "taxkernel_dry_prod.db"
    _bare_devices_db(db_path)
    before = db_path.read_bytes()

    assert runner.main(["--db", str(db_path), "--dry-run"]) == 0
    assert db_path.read_bytes() == before
