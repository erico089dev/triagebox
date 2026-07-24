"""Small dependency-free utilities."""

import os
import time

# Crockford base32 alphabet (per the ULID spec)
_B32 = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def ulid() -> str:
    """ULID: 48-bit timestamp (ms) + 80 random bits, sortable by time."""
    value = (int(time.time() * 1000) << 80) | int.from_bytes(os.urandom(10), "big")
    return "".join(_B32[(value >> (5 * i)) & 31] for i in range(25, -1, -1))
