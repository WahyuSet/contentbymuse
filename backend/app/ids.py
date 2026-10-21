import os
import time

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _encode(value: int, length: int) -> str:
    chars = []
    for _ in range(length):
        value, rem = divmod(value, 32)
        chars.append(_ALPHABET[rem])
    return "".join(reversed(chars))


def new_ulid(now_ms: int | None = None) -> str:
    """ULID: 48-bit millisecond timestamp + 80-bit randomness, Crockford Base32."""
    timestamp = int(time.time() * 1000) if now_ms is None else now_ms
    randomness = int.from_bytes(os.urandom(10), "big")
    return _encode(timestamp, 10) + _encode(randomness, 16)
