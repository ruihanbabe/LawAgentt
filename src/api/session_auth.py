"""匿名会话 Token 的哈希绑定与常量时间验证。"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from threading import RLock


@dataclass(frozen=True, slots=True)
class TokenBinding:
    salt: bytes
    token_hash: bytes


class InMemoryTokenBindingStore:
    """MVP 存储；仅保存随机盐和派生哈希，不保存 Token 原文。"""

    def __init__(self) -> None:
        self._bindings: dict[str, TokenBinding] = {}
        self._lock = RLock()

    def authenticate_or_bind(self, user_id: str, token: str) -> bool:
        with self._lock:
            current = self._bindings.get(user_id)
            if current is None:
                salt = secrets.token_bytes(16)
                self._bindings[user_id] = TokenBinding(
                    salt=salt,
                    token_hash=_derive_token_hash(token, salt),
                )
                return True
            candidate = _derive_token_hash(token, current.salt)
            return hmac.compare_digest(candidate, current.token_hash)

    def delete(self, user_id: str) -> bool:
        with self._lock:
            return self._bindings.pop(user_id, None) is not None

def _derive_token_hash(token: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        token.encode("utf-8"),
        salt=salt,
        n=2**14,
        r=8,
        p=1,
        dklen=32,
    )


__all__ = ["InMemoryTokenBindingStore", "TokenBinding"]
