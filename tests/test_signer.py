"""Tests for Kalshi RSA-PSS request signing."""

import base64

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from engine.auth.signer import KalshiSigner


def _make_key_pem() -> tuple[rsa.RSAPrivateKey, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    return key, pem


def test_signature_verifies_with_public_key():
    key, pem = _make_key_pem()
    signer = KalshiSigner("api-key-id", pem)
    ts, method, path = "1700000000000", "GET", "/trade-api/v2/portfolio/balance"
    sig_b64 = signer.sign(ts, method, path)
    message = f"{ts}{method}{path}".encode()
    # Verify with the public key; raises if invalid.
    key.public_key().verify(
        base64.b64decode(sig_b64),
        message,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.DIGEST_LENGTH),
        hashes.SHA256(),
    )


def test_headers_contain_required_fields():
    _, pem = _make_key_pem()
    signer = KalshiSigner("my-id", pem)
    headers = signer.headers("POST", "/trade-api/v2/portfolio/orders")
    assert headers["KALSHI-ACCESS-KEY"] == "my-id"
    assert headers["KALSHI-ACCESS-TIMESTAMP"].isdigit()
    assert len(headers["KALSHI-ACCESS-TIMESTAMP"]) == 13  # milliseconds
    assert headers["KALSHI-ACCESS-SIGNATURE"]


def test_path_without_query():
    assert (
        KalshiSigner.path_without_query("/trade-api/v2/markets?limit=10&x=1")
        == "/trade-api/v2/markets"
    )
