"""Tests for the LLM meta-layer: token budget + provider failover.

Network is never touched — the provider HTTP calls are monkeypatched.
"""

import pytest

from engine.llm.meta import LLMMetaLayer, TokenBudget, MetaGuidance


def test_token_budget_tracks_and_caps():
    b = TokenBudget(daily_limit=100)
    assert not b.over and b.remaining() == 100
    b.add(60)
    assert not b.over and b.remaining() == 40
    b.add(50)
    assert b.over and b.remaining() == 0


def test_token_budget_unlimited_when_zero():
    b = TokenBudget(daily_limit=0)
    b.add(10_000_000)
    assert not b.over and b.remaining() == -1


@pytest.mark.asyncio
async def test_advise_disabled_without_keys():
    llm = LLMMetaLayer()  # no keys
    g = await llm.advise({"x": 1})
    assert g.source == "default"
    await llm.close()


@pytest.mark.asyncio
async def test_advise_paused_when_over_budget():
    llm = LLMMetaLayer(anthropic_key="k", daily_token_budget=10)
    llm.budget.add(20)  # blow the budget
    g = await llm.advise({"x": 1})
    assert g.source == "budget" and "budget" in g.note
    await llm.close()


@pytest.mark.asyncio
async def test_advise_fails_over_to_claude(monkeypatch):
    # Gemini is primary; if it errors we fail over to Claude.
    llm = LLMMetaLayer(anthropic_key="k", gemini_key="g", daily_token_budget=0)

    async def gemini_fail(*a, **k):
        return None

    async def claude_ok(system, prompt, model, max_tokens):
        return '{"regime":"calm","risk_dial":0.8,"active_strategy":"edge","note":"ok"}'

    monkeypatch.setattr(llm, "_call_gemini", gemini_fail)
    monkeypatch.setattr(llm, "_call_claude", claude_ok)
    g = await llm.advise({"x": 1})
    assert g.source == "claude" and g.risk_dial == pytest.approx(0.8)
    await llm.close()


@pytest.mark.asyncio
async def test_advise_prefers_gemini_no_double_call(monkeypatch):
    llm = LLMMetaLayer(anthropic_key="k", gemini_key="g", daily_token_budget=0)
    calls = {"claude": 0, "gemini": 0}

    async def gemini_ok(system, prompt, max_tokens):
        calls["gemini"] += 1
        return '{"regime":"trending","risk_dial":1.1,"active_strategy":"edge","note":"x"}'

    async def claude_ok(system, prompt, model, max_tokens):
        calls["claude"] += 1
        return '{"regime":"calm","risk_dial":0.5,"active_strategy":"edge","note":"y"}'

    monkeypatch.setattr(llm, "_call_gemini", gemini_ok)
    monkeypatch.setattr(llm, "_call_claude", claude_ok)
    g = await llm.advise({"x": 1})
    # Gemini (primary) succeeded -> Claude must NOT be called.
    assert g.source == "gemini" and calls == {"claude": 0, "gemini": 1}
    await llm.close()
