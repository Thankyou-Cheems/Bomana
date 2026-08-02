"""Repository-owned trust contract for CheemsPay subscription receipts.

The public key is intentionally tracked: it is a verification trust root, not
a signing secret.  The matching private key remains owned by CheemsPay and is
never part of Bomana source or release inputs.

The primary key is immutable for the lifetime of the distributed Launcher.
Any emergency replacement must be additive and retain this key until every
Launcher that trusts it has reached its support floor.
"""

from __future__ import annotations

from typing import Final

CHEEMSPAY_LICENSE_KEY_ID: Final = "prod-2026-01"
CHEEMSPAY_LICENSE_PUBLIC_KEY_DER_BASE64URL: Final = (
    "MCowBQYDK2VwAyEAN30P0bd6DN_fP7iMf1qkzBBkssGMHj0b18B81TsW6n8"
)

# Keep the primary entry forever.  New trust roots, if ever required, may be
# appended under a new key id, but this entry must not be replaced or removed.
CHEEMSPAY_LICENSE_PUBLIC_KEYS: Final = {
    CHEEMSPAY_LICENSE_KEY_ID: CHEEMSPAY_LICENSE_PUBLIC_KEY_DER_BASE64URL,
}

__all__ = [
    "CHEEMSPAY_LICENSE_KEY_ID",
    "CHEEMSPAY_LICENSE_PUBLIC_KEY_DER_BASE64URL",
    "CHEEMSPAY_LICENSE_PUBLIC_KEYS",
]
