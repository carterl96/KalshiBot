"""Kalshi RSA-PSS request signing.

Kalshi authenticates API requests with an RSA-PSS SHA256 signature over the
string `timestamp_ms + HTTP_METHOD + request_path`. The path must be signed
WITHOUT query parameters. Three headers are sent on every authenticated request:

    KALSHI-ACCESS-KEY        the API key id
    KALSHI-ACCESS-TIMESTAMP  current unix time in MILLISECONDS
    KALSHI-ACCESS-SIGNATURE  base64(RSA-PSS-SHA256 signature)
"""

from __future__ import annotations

import base64
import time

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa


class KalshiSigner:
    """Signs requests with an RSA private key per Kalshi's scheme."""

    def __init__(self, api_key_id: str, private_key_pem: str):
        self.api_key_id = api_key_id
        self._key = self._load_key(private_key_pem)

    @staticmethod
    def _load_key(pem: str) -> rsa.RSAPrivateKey:
        key = serialization.load_pem_private_key(pem.encode("utf-8"), password=None)
        if not isinstance(key, rsa.RSAPrivateKey):
            raise ValueError("Kalshi private key must be an RSA key")
        return key

    def sign(self, timestamp_ms: str, method: str, path: str) -> str:
        """Return the base64 RSA-PSS signature for one request.

        `path` is the path component only (no query string), e.g.
        ``/trade-api/v2/portfolio/balance``.
        """
        message = f"{timestamp_ms}{method.upper()}{path}".encode("utf-8")
        signature = self._key.sign(
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                # Kalshi uses the digest length as the salt length.
                salt_length=padding.PSS.DIGEST_LENGTH,
            ),
            hashes.SHA256(),
        )
        return base64.b64encode(signature).decode("utf-8")

    def headers(self, method: str, path: str) -> dict[str, str]:
        """Build the full set of auth headers for a request."""
        ts = str(int(time.time() * 1000))
        return {
            "KALSHI-ACCESS-KEY": self.api_key_id,
            "KALSHI-ACCESS-TIMESTAMP": ts,
            "KALSHI-ACCESS-SIGNATURE": self.sign(ts, method, path),
        }

    @staticmethod
    def path_without_query(full_path: str) -> str:
        """Strip the query string from a path before signing."""
        return full_path.split("?", 1)[0]
