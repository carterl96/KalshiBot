"""Tests for the encrypted operator settings store."""

import pytest

from engine.config import Settings
from engine.settings_store import SettingsManager
from engine.telemetry.store import Store


@pytest.fixture
async def mgr():
    store = Store("sqlite+aiosqlite:///:memory:")
    await store.init()
    yield SettingsManager(store, app_secret="unit-test-secret")
    await store.close()


async def test_secret_round_trip_and_masking(mgr):
    await mgr.save({"kalshi_private_key": "SUPER-SECRET-KEY-1234"})
    # Overrides decrypt back to the original.
    ov = await mgr.overrides()
    assert ov["kalshi_private_key"] == "SUPER-SECRET-KEY-1234"
    # Public view never exposes the plaintext.
    pub = await mgr.public_view()
    assert pub["kalshi_private_key"]["set"] is True
    assert pub["kalshi_private_key"]["hint"] == "••••1234"
    assert "SUPER-SECRET" not in str(pub)


async def test_encrypted_at_rest(mgr):
    await mgr.save({"anthropic_api_key": "sk-ant-abc"})
    raw = await mgr.store.get_app_settings()
    assert raw["anthropic_api_key"].startswith("enc::")
    assert "sk-ant-abc" not in raw["anthropic_api_key"]


async def test_blank_secret_does_not_wipe(mgr):
    await mgr.save({"gemini_api_key": "g-123"})
    await mgr.save({"gemini_api_key": ""})  # blank submit
    ov = await mgr.overrides()
    assert ov["gemini_api_key"] == "g-123"


async def test_clear_sentinel_removes_secret(mgr):
    await mgr.save({"gemini_api_key": "g-123"})
    await mgr.save({"gemini_api_key": "__clear__"})
    ov = await mgr.overrides()
    assert "gemini_api_key" not in ov


async def test_plain_field_coercion(mgr):
    await mgr.save({"starting_balance": "2500", "llm_enabled": "true",
                    "kalshi_env": "prod"})
    ov = await mgr.overrides()
    assert ov["starting_balance"] == 2500.0
    assert ov["llm_enabled"] is True
    assert ov["kalshi_env"] == "prod"


async def test_effective_overlays_base(mgr):
    await mgr.save({"kalshi_env": "prod", "min_edge": "0.07"})
    base = Settings(kalshi_env="demo", min_edge=0.04)
    eff = await mgr.effective(base)
    assert eff.kalshi_env == "prod"
    assert eff.min_edge == 0.07
    # Property recomputes from the override.
    assert "elections" in eff.rest_base
