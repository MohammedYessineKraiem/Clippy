from __future__ import annotations

import base64
import os
import threading
import time
from collections.abc import Callable

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


class VaultError(RuntimeError):
    pass


class VaultLockedError(VaultError):
    pass


class InvalidPassphraseError(VaultError):
    pass


def new_salt() -> bytes:
    return os.urandom(16)


def derive_key(passphrase: str, salt: bytes) -> bytes:
    if not passphrase:
        raise ValueError("Passphrase cannot be empty")
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=600_000)
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode("utf-8")))


class VaultManager:
    """Keeps the derived vault key in memory only while the vault is unlocked."""

    VERIFY_TEXT = b"clippy-vault-verifier-v1"

    def __init__(self, auto_lock_seconds: int = 60) -> None:
        self.auto_lock_seconds = auto_lock_seconds
        self._fernet: Fernet | None = None
        self._last_activity = 0.0
        self._lock = threading.RLock()
        self._listeners: list[Callable[[], None]] = []

    @property
    def is_unlocked(self) -> bool:
        with self._lock:
            self._expire_if_needed()
            return self._fernet is not None

    def add_lock_listener(self, callback: Callable[[], None]) -> None:
        self._listeners.append(callback)

    def initialize(self, passphrase: str, salt: bytes) -> bytes:
        fernet = Fernet(derive_key(passphrase, salt))
        verifier = fernet.encrypt(self.VERIFY_TEXT)
        with self._lock:
            self._fernet = fernet
            self.touch()
        return verifier

    def unlock(self, passphrase: str, salt: bytes, verifier: bytes) -> None:
        fernet = Fernet(derive_key(passphrase, salt))
        try:
            if fernet.decrypt(verifier) != self.VERIFY_TEXT:
                raise InvalidPassphraseError("Invalid vault passphrase")
        except InvalidToken as exc:
            raise InvalidPassphraseError("Invalid vault passphrase") from exc
        with self._lock:
            self._fernet = fernet
            self.touch()

    def lock(self) -> None:
        with self._lock:
            was_unlocked = self._fernet is not None
            self._fernet = None
            self._last_activity = 0.0
        if was_unlocked:
            for callback in self._listeners:
                callback()

    def touch(self) -> None:
        self._last_activity = time.monotonic()

    def encrypt(self, value: bytes) -> bytes:
        fernet = self._require_unlocked()
        self.touch()
        return fernet.encrypt(value)

    def decrypt(self, value: bytes) -> bytes:
        fernet = self._require_unlocked()
        try:
            plain = fernet.decrypt(value)
        except InvalidToken as exc:
            raise VaultError("Vault data could not be decrypted") from exc
        self.touch()
        return plain

    def _require_unlocked(self) -> Fernet:
        with self._lock:
            self._expire_if_needed()
            if self._fernet is None:
                raise VaultLockedError("Vault is locked")
            return self._fernet

    def _expire_if_needed(self) -> None:
        if (
            self._fernet is not None
            and self.auto_lock_seconds > 0
            and time.monotonic() - self._last_activity >= self.auto_lock_seconds
        ):
            self._fernet = None
