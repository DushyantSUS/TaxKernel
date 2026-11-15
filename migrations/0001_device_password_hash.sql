-- M1: store Argon2id hashes for device passwords.
--
-- Additive only: the legacy plaintext column is kept so a one-release rollback
-- is possible. intel/passwords.py backfills the hash and nulls the plaintext.
--
-- Applied by migrations/run.py; never executed by hand.

ALTER TABLE devices ADD COLUMN device_password_hash TEXT;
