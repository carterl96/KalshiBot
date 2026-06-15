"""User-configurable settings persisted from the Setup page.

This lets an operator configure Kalshi credentials, AI keys, and trading
parameters through the web UI instead of editing environment variables — the
foundation for a friendly setup experience (and, later, SaaS onboarding).

Secret values (private key, API keys) are encrypted at rest with Fernet, using
a key derived from ``APP_SECRET``. Secrets are NEVER returned to the browser in
plaintext: the public view only reports whether each secret is set plus a short
masked hint.

Effective configuration = base environment ``Settings`` overlaid with whatever
the operator saved in the database, so env vars act as defaults/fallbacks.
"""

from __future__ import annotations

import base64
import hashlib
import logging
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from engine.config import Settings
from engine.telemetry.store import Store

log = logging.getLogger("settings")

# Fields the operator may set, grouped by whether they are secret.
SECRET_FIELDS = {
    "kalshi_api_key_id",
    "kalshi_private_key",
    "anthropic_api_key",
    "gemini_api_key",
}
# Non-secret fields with their type coercion.
PLAIN_FIELDS: dict[str, type] = {
    "kalshi_env": str,
    "series": str,
    "start_mode": str,
    "autostart": bool,
    "starting_balance": float,
    "llm_enabled": bool,
    "min_edge": float,
    "fee_buffer": float,
    "vol_lookback_s": int,
}
ALL_FIELDS = SECRET_FIELDS | set(PLAIN_FIELDS)

# Prefix marking an encrypted value in the DB.
ENC_PREFIX = "enc::"


def _coerce(field: str, value: Any) -> Any:
    if field in PLAIN_FIELDS:
        typ = PLAIN_FIELDS[field]
        if typ is bool:
            return value in (True, "true", "True", "1", 1, "on")
        try:
            return typ(value)
        except (TypeError, ValueError):
            return value
    return value


def _mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 4:
        return "••••"
    return f"••••{value[-4:]}"


class SettingsManager:
    def __init__(self, store: Store, app_secret: str):
        self.store = store
        self._fernet = Fernet(self._derive_key(app_secret))

    @staticmethod
    def _derive_key(secret: str) -> bytes:
        digest = hashlib.sha256(secret.encode("utf-8")).digest()
        return base64.urlsafe_b64encode(digest)

    def _encrypt(self, value: str) -> str:
        return ENC_PREFIX + self._fernet.encrypt(value.encode("utf-8")).decode()

    def _decrypt(self, stored: str) -> str:
        if not stored.startswith(ENC_PREFIX):
            return stored
        try:
            return self._fernet.decrypt(stored[len(ENC_PREFIX):].encode()).decode()
        except InvalidToken:
            log.warning("could not decrypt a stored secret (APP_SECRET changed?)")
            return ""

    async def overrides(self) -> dict[str, Any]:
        """Decrypted, type-coerced operator overrides for the engine."""
        raw = await self.store.get_app_settings()
        out: dict[str, Any] = {}
        for key, stored in raw.items():
            if key not in ALL_FIELDS:
                continue
            value = self._decrypt(stored) if key in SECRET_FIELDS else stored
            if value == "":
                continue
            out[key] = _coerce(key, value)
        return out

    async def public_view(self) -> dict[str, Any]:
        """Settings safe to send to the browser (secrets masked)."""
        raw = await self.store.get_app_settings()
        view: dict[str, Any] = {}
        for field in PLAIN_FIELDS:
            view[field] = (
                _coerce(field, raw[field]) if field in raw and raw[field] != "" else None
            )
        for field in SECRET_FIELDS:
            decrypted = self._decrypt(raw.get(field, "")) if raw.get(field) else ""
            view[field] = {"set": bool(decrypted), "hint": _mask(decrypted)}
        return view

    async def save(self, payload: dict[str, Any]) -> None:
        """Persist a partial settings payload. Empty secret strings are ignored
        so the UI can submit blanks without wiping existing secrets; the literal
        value ``"__clear__"`` removes a secret."""
        to_store: dict[str, str] = {}
        for key, value in payload.items():
            if key not in ALL_FIELDS:
                continue
            if key in SECRET_FIELDS:
                if value in (None, ""):
                    continue  # leave existing secret untouched
                if value == "__clear__":
                    to_store[key] = ""
                else:
                    to_store[key] = self._encrypt(str(value))
            else:
                to_store[key] = "" if value is None else str(value)
        if to_store:
            await self.store.set_app_settings(to_store)

    async def effective(self, base: Settings) -> Settings:
        """Base env settings overlaid with operator overrides."""
        overrides = await self.overrides()
        if not overrides:
            return base
        return base.model_copy(update=overrides)
