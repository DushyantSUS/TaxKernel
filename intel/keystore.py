"""OS-keystore backed key material (milestone M1).

Keys used to live in plaintext files next to the code:

* ``.taxkernel_vault.key`` — AES-256-GCM master key
* ``.taxkernel_did.key``   — secp256r1 private key (PEM)

This module moves them into the operating system keystore via ``keyring``
(Window Vault / DPAPI on this host, Secret Service on Linux, Keychain on
macOS). The frozen modules ``crypto_vault.py`` and ``ssi_vault.py`` keep their
cipher and DID logic unchanged; :mod:`intel.vault` injects the key source.

Design rules
------------
* **Read-through migration.** If a key exists on disk it is copied into the
  keystore on first access and the same bytes are returned, so existing
  ciphertext keeps decrypting.
* **One-release fallback.** If the keystore is unavailable, callers may still
  read the on-disk key with a loud warning (:func:`get_master_key` with
  ``allow_disk_fallback=True``).
* **Never silently regenerate a key that already exists somewhere.**
  Generating is only allowed when both the keystore and the disk are empty.
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path

import keyring

import crypto_vault
import ssi_vault
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

#: ``keyring`` service name. Must stay stable: it addresses existing secrets.
SERVICE = "TaxKernel"
#: ``keyring`` user names (one secret per entry).
MASTER_KEY_USER = "master"
DID_KEY_USER = "did"

LOG = logging.getLogger("taxkernel.keystore")

#: Paths are taken from the frozen modules so migration can never drift from
#: the file those modules actually read.
VAULT_KEY_FILE = Path(crypto_vault.KEY_FILE)
DID_KEY_FILE = Path(ssi_vault.KEY_FILE)

_VALID_AES_KEY_LENGTHS = frozenset({16, 24, 32})


class KeystoreUnavailable(RuntimeError):
    """Raised when the OS keystore cannot be used."""


# --------------------------------------------------------------------------- #
# Backend introspection
# --------------------------------------------------------------------------- #

def backend_name() -> str:
    """Name of the active ``keyring`` backend, or ``"unavailable"``."""
    try:
        return type(keyring.get_keyring()).__name__
    except Exception:  # pragma: no cover - backend discovery is best effort
        return "unavailable"


def is_available() -> bool:
    """True when a real keystore backend is active (not ``fail.Keyring``)."""
    try:
        from keyring.backends.fail import Keyring as FailKeyring

        return not isinstance(keyring.get_keyring(), FailKeyring)
    except Exception:  # pragma: no cover
        return False


# --------------------------------------------------------------------------- #
# Secret primitives
# --------------------------------------------------------------------------- #

def _read_secret(user: str) -> bytes | None:
    try:
        stored = keyring.get_password(SERVICE, user)
    except Exception as exc:  # backend errors, locked vault, policy
        raise KeystoreUnavailable(f"keystore read failed for {user!r}: {exc}") from exc
    if stored is None:
        return None
    try:
        return base64.b64decode(stored.encode("ascii"), validate=True)
    except Exception as exc:
        raise KeystoreUnavailable(
            f"keystore entry {user!r} is not valid base64"
        ) from exc


def _write_secret(user: str, value: bytes) -> None:
    payload = base64.b64encode(value).decode("ascii")
    try:
        keyring.set_password(SERVICE, user, payload)
    except Exception as exc:
        raise KeystoreUnavailable(f"keystore write failed for {user!r}: {exc}") from exc


def _delete_secret(user: str) -> None:
    try:
        keyring.delete_password(SERVICE, user)
    except Exception:  # already absent / backend refuses; both are harmless
        LOG.debug("keystore delete skipped for %r", user)


def _read_disk(path: Path) -> bytes | None:
    try:
        if path.is_file():
            return path.read_bytes()
    except OSError as exc:  # pragma: no cover - permission problems
        raise KeystoreUnavailable(f"cannot read {path.name}: {exc}") from exc
    return None


def _validate_master_key(raw: bytes) -> bytes:
    if len(raw) not in _VALID_AES_KEY_LENGTHS:
        raise KeystoreUnavailable(
            f"master key has invalid length {len(raw)} (expected 16/24/32 bytes)"
        )
    return raw


def _validate_pem(raw: bytes) -> bytes:
    if b"-----BEGIN" not in raw:
        raise KeystoreUnavailable("DID key material is not PEM encoded")
    return raw


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def get_master_key(*, allow_disk_fallback: bool = True) -> bytes:
    """Return the 32-byte AES-256-GCM master key.

    Order of resolution:

    1. OS keystore (fast path).
    2. On-disk ``.taxkernel_vault.key`` — copied into the keystore, and the
       same bytes returned so pre-existing ciphertext is unaffected.
    3. Newly generated key, stored only in the keystore.

    Raises :class:`KeystoreUnavailable` when the keystore cannot be used and
    ``allow_disk_fallback`` is false or no disk key exists.
    """
    try:
        existing = _read_secret(MASTER_KEY_USER)
    except KeystoreUnavailable:
        if allow_disk_fallback:
            LOG.warning(
                "OS keystore unavailable; reading master key from %s (insecure fallback)",
                VAULT_KEY_FILE.name,
            )
            disk = _read_disk(VAULT_KEY_FILE)
            if disk is not None:
                return _validate_master_key(disk)
        raise

    if existing is not None:
        return _validate_master_key(existing)

    disk = _read_disk(VAULT_KEY_FILE)
    if disk is not None:
        key = _validate_master_key(disk)
        _write_secret(MASTER_KEY_USER, key)
        LOG.warning(
            "migrated master key from %s into the OS keystore", VAULT_KEY_FILE.name
        )
        return key

    generated = AESGCM.generate_key(bit_length=256)
    _write_secret(MASTER_KEY_USER, generated)
    LOG.info("generated a new master key in the OS keystore")
    return generated


def get_or_create_did_key_pem(*, allow_disk_fallback: bool = True) -> bytes:
    """Return the secp256r1 private key as PEM bytes.

    Same resolution order as :func:`get_master_key`. The DID string derived by
    ``ssi_vault.py`` is unchanged because the key bytes are unchanged.
    """
    try:
        existing = _read_secret(DID_KEY_USER)
    except KeystoreUnavailable:
        if allow_disk_fallback:
            LOG.warning(
                "OS keystore unavailable; reading DID key from %s (insecure fallback)",
                DID_KEY_FILE.name,
            )
            disk = _read_disk(DID_KEY_FILE)
            if disk is not None:
                return _validate_pem(disk)
        raise

    if existing is not None:
        return _validate_pem(existing)

    disk = _read_disk(DID_KEY_FILE)
    if disk is not None:
        pem = _validate_pem(disk)
        _write_secret(DID_KEY_USER, pem)
        LOG.warning("migrated DID key from %s into the OS keystore", DID_KEY_FILE.name)
        return pem

    # No key anywhere: let the frozen vault generate one, then capture it.
    pem = _generate_did_key_pem()
    _write_secret(DID_KEY_USER, pem)
    LOG.info("generated a new DID key in the OS keystore")
    return pem


def _generate_did_key_pem() -> bytes:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    key = ec.generate_private_key(ec.SECP256R1())
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def migrate_from_disk(*, delete_disk: bool = True) -> dict[str, str]:
    """Copy on-disk key material into the keystore.

    Each secret is verified by reading it back before the file is removed, so a
    failed write never destroys the only copy.

    Returns a per-secret status: ``"migrated"``, ``"staged"`` (copied but file
    kept), or ``"absent"``.
    """
    results: dict[str, str] = {}
    plan = (
        ("master_key", VAULT_KEY_FILE, MASTER_KEY_USER),
        ("did_key", DID_KEY_FILE, DID_KEY_USER),
    )
    for label, path, user in plan:
        raw = _read_disk(path)
        if raw is None:
            results[label] = "absent"
            continue
        # Validate before storing; a corrupt file must not shadow a good secret.
        if user == MASTER_KEY_USER:
            raw = _validate_master_key(raw)
        else:
            raw = _validate_pem(raw)

        _write_secret(user, raw)
        if _read_secret(user) != raw:
            raise KeystoreUnavailable(f"keystore verification failed for {label}")

        if delete_disk:
            try:
                path.unlink()
            except OSError as exc:  # pragma: no cover
                LOG.error("could not remove %s: %s", path.name, exc)
                results[label] = "staged"
                continue
            results[label] = "migrated"
        else:
            results[label] = "staged"

    return results


def purge_disk_keys() -> list[str]:
    """Delete leftover plaintext key files. Returns the names removed."""
    removed: list[str] = []
    for path in (VAULT_KEY_FILE, DID_KEY_FILE):
        try:
            if path.is_file():
                path.unlink()
                removed.append(path.name)
        except OSError as exc:  # pragma: no cover
            LOG.error("could not remove %s: %s", path.name, exc)
    return removed


def status() -> dict[str, object]:
    """Non-secret status snapshot for ``GET /intel/health``."""
    available = is_available()

    def presence(user: str) -> str:
        if not available:
            return "unknown"
        try:
            return "present" if _read_secret(user) is not None else "missing"
        except KeystoreUnavailable:
            return "error"

    return {
        "service": SERVICE,
        "backend": backend_name(),
        "available": available,
        "master_key": presence(MASTER_KEY_USER),
        "did_key": presence(DID_KEY_USER),
        "disk_master_key_present": VAULT_KEY_FILE.is_file(),
        "disk_did_key_present": DID_KEY_FILE.is_file(),
    }
