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

import httpx

log = logging.getLogger("llm")

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "{model}:generateContent"
)

DEFAULT_CLAUDE_MODEL = "claude-sonnet-4-6"
DEFAULT_GEMINI_MODEL = "gemini-2.5-pro"

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
    "You are a quantitative analyst reviewing a trading bot's calibration data "
    "and recent losses. Propose parameter adjustments to improve edge and EV. "
    "Respond ONLY with JSON: "
    '{"description": "<1-2 sentences explaining why>", '
    '"params": {"min_edge": <float|null>, "kelly_fraction": <float|null>, '
    '"fee_buffer": <float|null>, "vol_lookback_s": <int|null>, '
    '"max_per_trade": <float|null>, "max_per_window": <float|null>}}. '
    "Omit any param you do not want to change (set it to null). "
    "Only suggest changes that are grounded in the data. "
    "Be conservative — small incremental improvements, not wild swings."
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
    ):
        self.anthropic_key = anthropic_key
        self.gemini_key = gemini_key
        self.claude_model = claude_model
        self.gemini_model = gemini_model
        self._client = httpx.AsyncClient(timeout=30.0)

    @property
    def enabled(self) -> bool:
        return bool(self.anthropic_key or self.gemini_key)

    async def close(self) -> None:
        await self._client.aclose()

    async def advise(self, context: dict) -> MetaGuidance:
        """Get guidance, preferring an ensemble of available models.

        Claude acts as primary; Gemini as a critic. We blend their risk dials
        (min, to stay conservative) and take the primary's regime/strategy.
        """
        if not self.enabled:
            return MetaGuidance()

        prompt = json.dumps(context, default=str)[:6000]
        results: list[MetaGuidance] = []

        if self.anthropic_key:
            g = await self._ask_claude(prompt)
            if g:
                results.append(g)
        if self.gemini_key:
            g = await self._ask_gemini(prompt)
            if g:
                results.append(g)

        if not results:
            return MetaGuidance(note="LLM call failed; using defaults")
        if len(results) == 1:
            return results[0]
        # Ensemble: conservative dial, primary (Claude/first) regime + strategy.
        primary = results[0]
        primary.risk_dial = min(r.risk_dial for r in results)
        primary.source = "+".join(r.source for r in results)
        primary.note = " | ".join(f"{r.source}: {r.note}" for r in results)
        return primary

    async def _ask_claude(self, prompt: str) -> MetaGuidance | None:
        try:
            resp = await self._client.post(
                ANTHROPIC_URL,
                headers={
                    "x-api-key": self.anthropic_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": self.claude_model,
                    "max_tokens": 256,
                    "system": SYSTEM_PROMPT,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            resp.raise_for_status()
            data = resp.json()
            text = "".join(
                block.get("text", "") for block in data.get("content", [])
            )
            return _parse_guidance(text, "claude")
        except Exception as exc:  # noqa: BLE001
            log.warning("Claude advise failed: %s", exc)
            return None

    async def propose_params(self, calibration_summary: dict, recent_losses: list[dict]) -> dict | None:
        """Ask the LLM to review calibration data and propose parameter tweaks.

        Returns a dict with ``description`` and ``params`` (partial dict of
        parameter overrides), or None if the call failed or LLM is disabled.
        """
        if not self.enabled:
            return None
        prompt = json.dumps(
            {"calibration": calibration_summary, "recent_losses": recent_losses},
            default=str,
        )[:6000]
        if self.anthropic_key:
            return await self._ask_claude_proposal(prompt)
        if self.gemini_key:
            return await self._ask_gemini_proposal(prompt)
        return None

    async def _ask_claude_proposal(self, prompt: str) -> dict | None:
        try:
            resp = await self._client.post(
                ANTHROPIC_URL,
                headers={
                    "x-api-key": self.anthropic_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": self.claude_model,
                    "max_tokens": 512,
                    "system": PROPOSAL_SYSTEM,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            resp.raise_for_status()
            data = resp.json()
            text = "".join(
                block.get("text", "") for block in data.get("content", [])
            )
            return _parse_proposal(text)
        except Exception as exc:  # noqa: BLE001
            log.warning("Claude proposal failed: %s", exc)
            return None

    async def _ask_gemini_proposal(self, prompt: str) -> dict | None:
        try:
            url = GEMINI_URL.format(model=self.gemini_model)
            resp = await self._client.post(
                url,
                params={"key": self.gemini_key},
                json={
                    "systemInstruction": {"parts": [{"text": PROPOSAL_SYSTEM}]},
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"maxOutputTokens": 512},
                },
            )
            resp.raise_for_status()
            data = resp.json()
            text = (
                data.get("candidates", [{}])[0]
                .get("content", {})
                .get("parts", [{}])[0]
                .get("text", "")
            )
            return _parse_proposal(text)
        except Exception as exc:  # noqa: BLE001
            log.warning("Gemini proposal failed: %s", exc)
            return None

    async def _ask_gemini(self, prompt: str) -> MetaGuidance | None:
        try:
            url = GEMINI_URL.format(model=self.gemini_model)
            resp = await self._client.post(
                url,
                params={"key": self.gemini_key},
                json={
                    "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"maxOutputTokens": 256},
                },
            )
            resp.raise_for_status()
            data = resp.json()
            text = (
                data.get("candidates", [{}])[0]
                .get("content", {})
                .get("parts", [{}])[0]
                .get("text", "")
            )
            return _parse_guidance(text, "gemini")
        except Exception as exc:  # noqa: BLE001
            log.warning("Gemini advise failed: %s", exc)
            return None
