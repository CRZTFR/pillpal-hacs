"""The Pill Pal lamp's signing and key derivation, with no Home Assistant in it.

Written against the lamp's device contract (contracts/device-v2 in the Bindicator
repository): integrations.md for the approval exchange, README.md for command tags.
tests/test_crypto.py checks every function here against that contract's fixture
vectors, which were generated independently of both the lamp and this integration.
"""
from __future__ import annotations

import hashlib
import hmac

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)

KEY_CONTEXT = "pill-pal/integration-key/v1"
CODE_CONTEXT = "pill-pal/integration-code/v1"
TAG_BYTES = 16


def framed(*parts: str | bytes) -> bytes:
    """Each part as its length in four big-endian bytes, then the part."""
    out = bytearray()
    for part in parts:
        data = part.encode() if isinstance(part, str) else part
        out += len(data).to_bytes(4, "big") + data
    return bytes(out)


def tag(key: bytes, data: bytes) -> str:
    """The lamp's 128-bit HMAC-SHA256 tag, as lowercase hex."""
    return hmac.new(key, data, hashlib.sha256).digest()[:TAG_BYTES].hex()


def read_tag(key: bytes, path: str, grant_id: int, nonce: str) -> str:
    """What an authenticated read signs: the path, the grant and a lamp nonce."""
    return tag(key, f"GET {path}\n{grant_id}\n{nonce}".encode())


class Approval:
    """One side of the approval exchange: a key pair made for one request."""

    def __init__(self, private_key: X25519PrivateKey | None = None) -> None:
        self._private = private_key or X25519PrivateKey.generate()
        self.public_key = self._private.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )

    @classmethod
    def from_private_bytes(cls, data: bytes) -> Approval:
        return cls(X25519PrivateKey.from_private_bytes(data))

    def shared(self, lamp_public_key: bytes) -> bytes:
        return self._private.exchange(X25519PublicKey.from_public_bytes(lamp_public_key))

    def derive(
        self, device_id: str, request_id: bytes, lamp_public_key: bytes
    ) -> tuple[bytes, str]:
        """The grant key and the six-digit code for this request."""
        shared = self.shared(lamp_public_key)
        parts = (device_id, request_id, lamp_public_key, self.public_key)
        key = hmac.new(shared, framed(KEY_CONTEXT, *parts), hashlib.sha256).digest()
        mac = hmac.new(shared, framed(CODE_CONTEXT, *parts), hashlib.sha256).digest()
        code = f"{int.from_bytes(mac[:4], 'big') % 1_000_000:06d}"
        return key, code
