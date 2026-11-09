from __future__ import annotations

import hashlib
import hmac
import os

DEFAULT_ITERATIONS = 600_000   # NFR-08 minimum


class Pbkdf2Hasher:
    """Salted PBKDF2-SHA256. Format: pbkdf2_sha256$<iterations>$<salt hex>$<hash hex>."""

    def __init__(self, iterations: int = DEFAULT_ITERATIONS):
        self.iterations = iterations

    def hash(self, secret: str) -> str:
        salt = os.urandom(16)
        digest = hashlib.pbkdf2_hmac("sha256", secret.encode(), salt, self.iterations)
        return f"pbkdf2_sha256${self.iterations}${salt.hex()}${digest.hex()}"

    def verify(self, secret: str, hashed: str) -> bool:
        try:
            scheme, iters, salt, expected = hashed.split("$")
            if scheme != "pbkdf2_sha256":
                return False
            digest = hashlib.pbkdf2_hmac("sha256", secret.encode(), bytes.fromhex(salt), int(iters))
            return hmac.compare_digest(digest.hex(), expected)
        except (ValueError, TypeError):
            return False
