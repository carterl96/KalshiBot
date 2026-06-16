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
    starting_balance: float = Field(default=1000.0)  # USD, paper bankroll
    max_per_trade: float = Field(default=20.0)        # USD notional per order
    max_per_window: float = Field(default=60.0)       # USD across a single market window
    daily_loss_limit: float = Field(default=50.0)     # USD; halts trading when hit
    max_exposure: float = Field(default=200.0)        # USD total open exposure
    max_drawdown_pct: float = Field(default=15.0)     # % from peak equity -> circuit break
    kelly_fraction: float = Field(default=0.25)       # fractional Kelly sizing

    # --- Strategy params ---
    min_edge: float = Field(default=0.04)             # required edge (prob units) net of buffer
    fee_buffer: float = Field(default=0.02)           # haircut for fees + half-spread
    vol_lookback_s: int = Field(default=900)          # spot vol estimation window (s)
    spot_symbol_btc: str = Field(default="BTC-USD")
    spot_symbol_eth: str = Field(default="ETH-USD")

    # --- LLM (Phase 2; optional) ---
    anthropic_api_key: str = Field(default="")
    gemini_api_key: str = Field(default="")
    llm_enabled: bool = Field(default=False)

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
