"""Argon2id password hashing for device credentials (milestone M1).

Device passwords were historically stored in plaintext
(``devices.device_password``). This module is the single place where they are
hashed and verified, so the algorithm and cost parameters can only change in
one spot.

Rules
-----
* Hash format is the standard Argon2 PHC string, so no custom encoding is
  needed and ``argon2-cffi`` can upgrade parameters later.
* An empty password is never hashed and never verifies.
* ``verify_password`` is total: it returns ``False`` for malformed input
  instead of raising, because it is called from request handlers.
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from argon2.low_level import Type

# Cost parameters are deliberately part of the public contract: tests assert
# them and ``needs_rehash`` compares against them.
TIME_COST = 3
MEMORY_COST = 65_536  # KiB -> 64 MiB
PARALLELISM = 4
HASH_LEN = 32
SALT_LEN = 16

#: Prefix shared by every Argon2id PHC hash.
HASH_PREFIX = "$argon2id$"

_HASHER: PasswordHasher = PasswordHasher(
    time_cost=TIME_COST,
    memory_cost=MEMORY_COST,
    parallelism=PARALLELISM,
    hash_len=HASH_LEN,
    salt_len=SALT_LEN,
    type=Type.ID,
)


class WeakPasswordError(ValueError):
    """Raised when a password is empty or otherwise unusable."""


def hash_password(password: str) -> str:
    """Return an Argon2id PHC hash for ``password``.

    Raises :class:`WeakPasswordError` for an empty/blank password rather than
    silently hashing it.
    """
    if not password or not password.strip():
        raise WeakPasswordError("password must not be empty")
    return _HASHER.hash(password)


def verify_password(stored: str | None, password: str) -> bool:
    """Constant-time verification of ``password`` against ``stored``.

    ``stored`` may be a PHC hash or a legacy plaintext value. Returns ``False``
    for empty inputs, malformed hashes, and mismatches.
    """
    if not stored or not password:
        return False
    if is_hash(stored):
        try:
            return _HASHER.verify(stored, password)
        except (VerificationError, InvalidHashError):
            return False
        except Exception:  # pragma: no cover - defensive: never 500 on auth
            return False
    # Legacy plaintext row (pre-M1). Compared in constant time so a timing
    # oracle cannot recover the password.
    return _constant_time_equals(stored, password)


def is_hash(value: str | None) -> bool:
    """True when ``value`` looks like an Argon2 PHC hash."""
    return value is not None and value.startswith(HASH_PREFIX)


def needs_rehash(stored: str | None) -> bool:
    """True when ``stored`` should be upgraded to current cost parameters."""
    if not is_hash(stored):
        return True
    assert stored is not None
    try:
        return bool(_HASHER.check_needs_rehash(stored))
    except (InvalidHashError, VerificationError):
        return True


def verify_device_credentials(
    plaintext: str | None,
    password_hash: str | None,
    attempt: str,
) -> bool:
    """Verify a device unlock attempt against stored material.

    ``password_hash`` wins when present; ``plaintext`` is only consulted as a
    one-release compatibility path for rows that predate M1. If neither is
    stored the device must re-pair, so the result is ``False``.
    """
    if password_hash:
        return verify_password(password_hash, attempt)
    if plaintext:
        return verify_password(plaintext, attempt)
    return False


def _constant_time_equals(left: str, right: str) -> bool:
    import hmac

    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))
