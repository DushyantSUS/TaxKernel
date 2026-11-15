"""Keystore-backed vaults (milestone M1).

``crypto_vault.py`` and ``ssi_vault.py`` are **frozen** by the migration plan
(key paths, cipher, DID format must not change). Subclassing them and
overriding only the key *source* is the smallest change that removes plaintext
key material from disk while keeping the ciphertext and DID bit-identical.

Only these two methods are overridden:

======================  =========================================
Frozen module           Overridden hook
======================  =========================================
``CryptoVault``         ``_load_or_create_key() -> bytes``
``SSIVault``            ``_load_or_generate_key() -> private key``
======================  =========================================
"""

from __future__ import annotations

import logging

from crypto_vault import CryptoVault
from cryptography.hazmat.primitives.asymmetric import ec
from ssi_vault import SSIVault

from intel import keystore

LOG = logging.getLogger("taxkernel.vault")


class KeystoreCryptoVault(CryptoVault):
    """``CryptoVault`` whose AES-256-GCM key comes from the OS keystore."""

    def _load_or_create_key(self) -> bytes:
        return keystore.get_master_key()


class KeystoreSSIVault(SSIVault):
    """``SSIVault`` whose secp256r1 key comes from the OS keystore."""

    def _load_or_generate_key(self) -> ec.EllipticCurvePrivateKey:
        from cryptography.hazmat.primitives import serialization

        pem = keystore.get_or_create_did_key_pem()
        key = serialization.load_pem_private_key(pem, password=None)
        if not isinstance(key, ec.EllipticCurvePrivateKey):
            raise keystore.KeystoreUnavailable("DID key is not an EC private key")
        return key


def build_crypto_vault(*, allow_disk_fallback: bool = True) -> CryptoVault:
    """Return a keystore-backed ``CryptoVault``.

    Falls back to the disk-keyed ``CryptoVault`` (with a warning) only when the
    keystore is unusable and ``allow_disk_fallback`` is true. Existing
    ciphertext always decrypts: the key bytes are migrated, not rotated.
    """
    try:
        return KeystoreCryptoVault()  # type: ignore[no-untyped-call]
    except keystore.KeystoreUnavailable as exc:
        if not allow_disk_fallback:
            raise
        LOG.warning("keystore unavailable, using on-disk vault key: %s", exc)
        return CryptoVault()  # type: ignore[no-untyped-call]


def build_ssi_vault(*, allow_disk_fallback: bool = True) -> SSIVault:
    """Return a keystore-backed ``SSIVault`` (same fallback contract)."""
    try:
        return KeystoreSSIVault()  # type: ignore[no-untyped-call]
    except keystore.KeystoreUnavailable as exc:
        if not allow_disk_fallback:
            raise
        LOG.warning("keystore unavailable, using on-disk DID key: %s", exc)
        return SSIVault()  # type: ignore[no-untyped-call]
