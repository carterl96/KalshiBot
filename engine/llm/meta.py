"""LLM meta-layer (Phase 2): slow, periodic strategic guidance.

This layer NEVER sits on the trade hot path. On a timer (every N seconds) it
sends a compact snapshot of recent market conditions and performance to one or
more LLMs (Claude via the Anthropic API, Gemini via Google's API) and asks for:

  * regime        - "trending" | "choppy" | "high_vol" | "calm"
  * risk_dial     - multiplier in [0, 1.5] applied to position sizing
  * active_strategy - which strategy profile to favor
  * note          - short human-readable rationale (also a post-trade review)

Results are advisory: the deterministic risk engine still enforces hard caps.
If no API keys are configured, the layer is disabled and returns neutral
defaults so the engine runs purely on the quant core.

Models are called directly over HTTP (httpx) to avoid extra SDK dependencies.
Model IDs are configurable; defaults reflect current Claude/Gemini families and
should be verified against the providers' docs before going live.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

log = logging.getLogger("llm")

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "{model}:generateContent"
)

# Cheap, fast models for the routine supervisor call. Override via settings;
# point the review model at a larger model if you want deeper periodic reviews.
DEFAULT_CLAUDE_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"


class TokenBudget:
    """Tracks LLM token usage against a hard daily cap (resets each UTC day).

    The meta-layer checks ``over`` before every call and stops spending once the
    budget is exhausted, so a runaway loop can't burn through the account.
    """

    def __init__(self, daily_limit: int):
        self.daily_limit = max(0, int(daily_limit))
        self._day = None
        self.used = 0

    def _roll(self) -> None:
        today = datetime.now(timezone.utc).date()
        if today != self._day:
            self._day = today
            self.used = 0

    def add(self, tokens: int) -> None:
        self._roll()
        self.used += max(0, int(tokens or 0))

    @property
    def over(self) -> bool:
        self._roll()
        return self.daily_limit > 0 and self.used >= self.daily_limit

    def remaining(self) -> int:
        self._roll()
        return -1 if self.daily_limit == 0 else max(0, self.daily_limit - self.used)

    def snapshot(self) -> dict:
        self._roll()
        return {
            "used": self.used,
            "daily_limit": self.daily_limit,
            "remaining": self.remaining(),
            "over_budget": self.over,
        }

SYSTEM_PROMPT = (
    "You are the risk/strategy supervisor for an automated Kalshi crypto "
    "trading bot. You do NOT place trades. Given recent market and performance "
    "context, respond ONLY with compact JSON: "
    '{"regime": "trending|choppy|high_vol|calm", '
    '"risk_dial": <float 0..1.5>, '
    '"active_strategy": "edge|near_close|conservative", '
    '"note": "<one sentence>"}. '
    "Be conservative after losses; risk_dial < 1 reduces position sizes."
)

PROPOSAL_SYSTEM = (
    "You are the autonomous self-tuning brain for a Kalshi crypto trading bot. "
    "You continuously improve the strategy from realized performance. You are "
    "given calibration data, recent losing trades, and the outcomes of your own "
    "past tuning changes (which were kept vs auto-reverted because they hurt "
    "EV). Propose ONE small, grounded adjustment to improve expected value net "
    "of fees. Respond ONLY with JSON: "
    '{"description": "<1-2 sentences explaining the reasoning>", '
    '"params": {"min_edge": <float|null>, "min_model_prob": <float|null>, '
    '"fee_buffer": <float|null>, "kelly_fraction": <float|null>, '
    '"stop_loss_drop": <float|null>, "vol_lookback_s": <int|null>}}. '
    "stop_loss_drop is the hard price stop (sell when bid drops this many "
    "probability points below entry price; default 0.18, range 0.05-0.35). "
    "min_model_prob filters entries below a conviction floor (0.0=disabled). "
    "Optimize EXPECTED VALUE, not win rate. Omit a param by setting it to null. "
    "Do NOT re-propose a change that was just reverted. Small incremental steps. "
    "Hard risk caps are not yours to change."
)


@dataclass
class MetaGuidance:
    regime: str = "calm"
    risk_dial: float = 1.0
    active_strategy: str = "edge"
    note: str = "default (LLM disabled)"
    source: str = "default"

    def to_dict(self) -> dict:
        return {
            "regime": self.regime,
            "risk_dial": self.risk_dial,
            "active_strategy": self.active_strategy,
            "note": self.note,
            "source": self.source,
        }


def _parse_proposal(text: str) -> dict | None:
    try:
        start = text.index("{")
        end = text.rindex("}") + 1
        obj = json.loads(text[start:end])
    except (ValueError, json.JSONDecodeError):
        return None
    desc = str(obj.get("description", ""))
    params_raw = obj.get("params", {}) or {}
    # Strip None values — keep only proposed changes.
    params = {k: v for k, v in params_raw.items() if v is not None}
    if not desc or not params:
        return None
    return {"description": desc, "params": params}


def _parse_guidance(text: str, source: str) -> MetaGuidance | None:
    try:
        start = text.index("{")
        end = text.rindex("}") + 1
        obj = json.loads(text[start:end])
    except (ValueError, json.JSONDecodeError):
        return None
    try:
        dial = float(obj.get("risk_dial", 1.0))
    except (TypeError, ValueError):
        dial = 1.0
    return MetaGuidance(
        regime=str(obj.get("regime", "calm")),
        risk_dial=max(0.0, min(1.5, dial)),
        active_strategy=str(obj.get("active_strategy", "edge")),
        note=str(obj.get("note", "")),
        source=source,
    )


class LLMMetaLayer:
    def __init__(
        self,
        anthropic_key: str = "",
        gemini_key: str = "",
        claude_model: str = DEFAULT_CLAUDE_MODEL,
        gemini_model: str = DEFAULT_GEMINI_MODEL,
        claude_review_model: str = "",
        daily_token_budget: int = 1_000_000,
    ):
        self.anthropic_key = anthropic_key
        self.gemini_key = gemini_key
        self.claude_model = claude_model
        self.gemini_model = gemini_model
        # Larger model for the periodic deep param-review; falls back to routine.
        self.claude_review_model = claude_review_model or claude_model
        self.budget = TokenBudget(daily_token_budget)
        self._client = httpx.AsyncClient(timeout=30.0)

    @property
    def enabled(self) -> bool:
        return bool(self.anthropic_key or self.gemini_key)

    def usage_snapshot(self) -> dict:
        return self.budget.snapshot()

    async def close(self) -> None:
        await self._client.aclose()

    # ---- generic provider calls (record token usage) ----

    async def _call_claude(self, system: str, prompt: str, model: str,
                           max_tokens: int) -> str | None:
        try:
            resp = await self._client.post(
                ANTHROPIC_URL,
                headers={
                    "x-api-key": self.anthropic_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": model,
                    "max_tokens": max_tokens,
                    "system": system,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            if resp.status_code >= 400:
                # Log the real Anthropic error body (e.g. bad model id, key
                # without access) instead of a generic status string.
                log.warning("Claude HTTP %s: %s", resp.status_code,
                            resp.text[:300])
                return None
            data = resp.json()
            usage = data.get("usage", {}) or {}
            self.budget.add(usage.get("input_tokens", 0) + usage.get("output_tokens", 0))
            return "".join(b.get("text", "") for b in data.get("content", []))
        except Exception as exc:  # noqa: BLE001
            log.warning("Claude call failed: %s", exc)
            return None

    async def _call_gemini(self, system: str, prompt: str,
                          max_tokens: int) -> str | None:
        try:
            url = GEMINI_URL.format(model=self.gemini_model)
            resp = await self._client.post(
                url,
                params={"key": self.gemini_key},
                json={
                    "systemInstruction": {"parts": [{"text": system}]},
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "maxOutputTokens": max_tokens,
                        "responseMimeType": "application/json",
                        # Gemini 2.5 models "think" by default, which silently
                        # eats the whole output budget and returns no text.
                        # Disable it — we want fast, deterministic JSON, not
                        # chain-of-thought.
                        "thinkingConfig": {"thinkingBudget": 0},
                    },
                },
            )
            resp.raise_for_status()
            data = resp.json()
            meta = data.get("usageMetadata", {}) or {}
            self.budget.add(meta.get("totalTokenCount", 0))
            cand = (data.get("candidates") or [{}])[0]
            parts = (cand.get("content", {}) or {}).get("parts", []) or []
            text = "".join(p.get("text", "") for p in parts)
            if not text:
                log.warning("Gemini returned no text (finishReason=%s)",
                            cand.get("finishReason"))
            return text
        except Exception as exc:  # noqa: BLE001
            log.warning("Gemini call failed: %s", exc)
            return None

    # ---- public API ----

    async def advise(self, context: dict) -> MetaGuidance:
        """Routine supervisor call. Gemini is primary (it's the strategy brain);
        Claude is the failover when Gemini errors. We do NOT call both every
        cycle — that doubled cost. Calls stop once the token budget is spent.
        """
        if not self.enabled:
            return MetaGuidance()
        if self.budget.over:
            return MetaGuidance(note="LLM paused: daily token budget reached",
                                source="budget")

        prompt = json.dumps(context, default=str)[:6000]
        if self.gemini_key:
            text = await self._call_gemini(SYSTEM_PROMPT, prompt, 256)
            g = _parse_guidance(text, "gemini") if text else None
            if g:
                return g
        if self.anthropic_key:
            text = await self._call_claude(
                SYSTEM_PROMPT, prompt, self.claude_model, 256
            )
            g = _parse_guidance(text, "claude") if text else None
            if g:
                return g
        return MetaGuidance(note="LLM call failed; using defaults")

    async def propose_params(
        self,
        calibration_summary: dict,
        recent_losses: list[dict],
        recent_outcomes: list[dict] | None = None,
    ) -> dict | None:
        """Periodic deep review: propose strategy-parameter tweaks from realized
        performance. Gemini is primary; Claude is the failover.

        ``recent_outcomes`` is the auto-tuner's memory (which past changes were
        kept vs reverted), so the AI doesn't keep re-proposing what already
        failed. Returns a dict with ``description`` and ``params``, or None.
        """
        if not self.enabled or self.budget.over:
            return None
        prompt = json.dumps(
            {
                "calibration": calibration_summary,
                "recent_losses": recent_losses,
                "past_tuning_outcomes": recent_outcomes or [],
            },
            default=str,
        )[:6000]
        if self.gemini_key:
            text = await self._call_gemini(PROPOSAL_SYSTEM, prompt, 512)
            p = _parse_proposal(text) if text else None
            if p:
                return p
        if self.anthropic_key:
            text = await self._call_claude(
                PROPOSAL_SYSTEM, prompt, self.claude_review_model, 512
            )
            return _parse_proposal(text) if text else None
        return None
