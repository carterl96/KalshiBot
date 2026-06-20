"""Central configuration loaded from environment variables.

All secrets (Kalshi RSA key, API key id, LLM keys, admin password) come from the
environment — never committed. See .env.example for the full list.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


# Kalshi environment base URLs. The "elections" host is the current production
# endpoint; the demo sandbox is used for safe testing.
KALSHI_HOSTS = {
    "prod": {
        "rest": "https://api.elections.kalshi.com/trade-api/v2",
        "ws": "wss://api.elections.kalshi.com/trade-api/ws/v2",
    },
    "demo": {
        "rest": "https://demo-api.kalshi.co/trade-api/v2",
        "ws": "wss://demo-api.kalshi.co/trade-api/ws/v2",
    },
}


class Settings(BaseSettings):
    """Engine settings. Field names map to upper-case env vars."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- Kalshi ---
    kalshi_env: str = Field(default="demo")  # "demo" or "prod"
    kalshi_api_key_id: str = Field(default="")
    # RSA private key (PEM). Provide the PEM contents directly, or a file path.
    kalshi_private_key: str = Field(default="")
    kalshi_private_key_path: str = Field(default="")

    # --- Trading mode & safety ---
    # Engine ALWAYS boots in paper mode. Live requires an explicit admin toggle.
    start_mode: str = Field(default="paper")  # "paper" | "live"
    autostart: bool = Field(default=False)

    # Which series to trade. Comma-separated Kalshi series prefixes.
    series: str = Field(default="KXBTC15M,KXBTCD")

    # --- Risk defaults (overridable at runtime via admin panel) ---
    # SAFE-BY-DEFAULT for live testing: tiny caps so the worst case is a few
    # dollars while the AI validates the edge on real fills. Scale these up from
    # the Controls page once realized EV is proven positive.
    starting_balance: float = Field(default=1000.0)  # USD, paper bankroll (unused live)
    max_per_trade: float = Field(default=2.0)         # USD notional per order
    max_per_window: float = Field(default=6.0)        # USD across a single market window
    daily_loss_limit: float = Field(default=5.0)      # USD; halts trading when hit
    max_exposure: float = Field(default=10.0)         # USD total open exposure
    max_drawdown_pct: float = Field(default=15.0)     # % from peak equity -> circuit break
    kelly_fraction: float = Field(default=0.25)       # fractional Kelly sizing

    # --- Strategy params ---
    min_edge: float = Field(default=0.04)             # required edge (prob units) net of buffer
    fee_buffer: float = Field(default=0.02)           # haircut for fees + half-spread
    # Minimum model confidence to take an entry. Filters out low-conviction
    # "cheap longshot" trades that show a tiny edge but a poor win probability,
    # which drag the green rate down. Profit still comes from edge; this just
    # keeps us in higher-conviction setups.
    min_model_prob: float = Field(default=0.58)
    vol_lookback_s: int = Field(default=900)          # spot vol estimation window (s)
    spot_symbol_btc: str = Field(default="BTC-USD")
    spot_symbol_eth: str = Field(default="ETH-USD")

    # --- Stop-loss (model-aware, anti-"cold-feet") ---
    # We exit a losing position when our *thesis* breaks (the model's fair
    # probability deteriorates), not on transient price noise. A wide hard price
    # stop remains as a catastrophe backstop.
    stop_model_floor: float = Field(default=0.35)     # cut if model_prob falls to/below this
    stop_model_drop: float = Field(default=0.25)      # ...or this far below entry model_prob
    stop_debounce: int = Field(default=6)             # adverse reads required before cutting
    stop_grace_s: float = Field(default=20.0)         # post-entry settle window (model stop only)
    stop_catastrophe_drop: float = Field(default=0.30)  # immediate hard price stop (any time)

    # --- LLM (Phase 2; optional) ---
    anthropic_api_key: str = Field(default="")
    gemini_api_key: str = Field(default="")
    llm_enabled: bool = Field(default=False)
    # Cost controls: cheap models for the routine 30s supervisor call, a larger
    # (configurable) model for the periodic deep param-review, and a hard daily
    # token budget the layer self-limits to. Claude is primary; Gemini is the
    # failover when Claude errors or the budget is exhausted on one provider.
    llm_model_claude: str = Field(default="claude-haiku-4-5-20251001")
    llm_model_claude_review: str = Field(default="claude-haiku-4-5-20251001")
    llm_model_gemini: str = Field(default="gemini-2.5-flash")
    llm_daily_token_budget: int = Field(default=1_000_000)  # 0 = unlimited

    # --- Autonomous self-tuning (the AI adapts the strategy itself) ---
    # When on, the LLM's parameter proposals are applied automatically (within
    # hard safety rails + auto-revert), instead of waiting for a manual click.
    llm_autotune_enabled: bool = Field(default=True)
    # Allow the AI to adapt the strategy while trading LIVE. On by default: the
    # AI is the point. It's bounded — it can only nudge whitelisted strategy
    # knobs within clamped ranges, never the hard risk caps, needs ~10 settled
    # windows before acting, and auto-reverts changes that hurt EV. With the
    # safe-by-default daily loss limit, the worst a bad tweak can do is capped.
    llm_autotune_live: bool = Field(default=True)
    # Settled windows to observe before judging (and possibly reverting) a change.
    llm_autotune_min_settles: int = Field(default=10)

    # --- Alerts (optional) ---
    # Discord/Slack-compatible incoming webhook URL.
    alert_webhook_url: str = Field(default="")
    # Fire an equity-drop alert when equity falls this many % from last high.
    alert_equity_drop_pct: float = Field(default=5.0)

    # --- Persistence ---
    database_url: str = Field(default="sqlite+aiosqlite:///./kalshibot.db")

    # --- API / auth ---
    admin_password: str = Field(default="changeme")
    jwt_secret: str = Field(default="dev-insecure-secret-change-me")
    # Used to derive the Fernet key that encrypts secrets at rest in the DB.
    app_secret: str = Field(default="dev-insecure-app-secret-change-me")
    cors_origins: str = Field(default="*")
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8000)

    @property
    def rest_base(self) -> str:
        return KALSHI_HOSTS[self.kalshi_env]["rest"]

    @property
    def ws_base(self) -> str:
        return KALSHI_HOSTS[self.kalshi_env]["ws"]

    @property
    def series_list(self) -> list[str]:
        return [s.strip() for s in self.series.split(",") if s.strip()]

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def load_private_key_pem(self) -> str:
        """Return the RSA private key PEM, from inline value or file path."""
        if self.kalshi_private_key:
            # Support escaped newlines when passed as a single-line env var.
            return self.kalshi_private_key.replace("\\n", "\n")
        if self.kalshi_private_key_path:
            with open(self.kalshi_private_key_path, "r", encoding="utf-8") as fh:
                return fh.read()
        return ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
