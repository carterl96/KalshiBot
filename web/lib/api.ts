// Typed client for the KalshiBot engine REST + WebSocket API.

export const ENGINE_URL =
  process.env.NEXT_PUBLIC_ENGINE_URL || "http://localhost:8000";
export const ENGINE_WS =
  process.env.NEXT_PUBLIC_ENGINE_WS || "ws://localhost:8000";

const TOKEN_KEY = "kalshibot_token";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}
export function setToken(token: string) {
  window.localStorage.setItem(TOKEN_KEY, token);
}
export function clearToken() {
  window.localStorage.removeItem(TOKEN_KEY);
}

// ---- Types (mirror the engine snapshots) ----
export interface Health {
  status: string;
  mode: "paper" | "live";
  engine_running: boolean;
  uptime_s: number;
  latency_ms: number;
  llm_enabled: boolean;
  has_credentials: boolean;
}

export interface RiskParams {
  max_per_trade: number;
  max_per_window: number;
  daily_loss_limit: number;
  max_exposure: number;
  max_drawdown_pct: number;
  kelly_fraction: number;
}

export interface Position {
  ticker: string;
  side: string;
  quantity: number;
  avg_price: number;
  current_price: number;
  unrealized_pnl: number;
}

export interface EngineState {
  mode: "paper" | "live";
  running: boolean;
  balance: number;
  equity: number;
  pnl_today: number;
  pnl_total: number;
  positions: Position[];
  active_strategy: string;
  risk_dial: number;
  circuit_broken: boolean;
  kill_switched: boolean;
  risk_params: RiskParams;
}

export interface Market {
  ticker: string;
  series: string;
  side: "up" | "down";
  strike: number;
  spot: number | null;
  kalshi_bid: number | null;
  kalshi_ask: number | null;
  mid: number | null;
  model_prob: number | null;
  edge: number | null;
  time_to_close_s: number;
}

export interface Trade {
  id: number;
  ts: number;
  ticker: string;
  side: string;
  action: string;
  quantity: number;
  price: number;
  mode: string;
  pnl: number;
  reason: string;
}

export interface Decision {
  id: number;
  ts: number;
  ticker: string;
  decision: string;
  model_prob: number;
  market_price: number;
  edge: number;
  action_taken: string;
  source: string;
  detail: string;
}

export interface EquityPoint {
  ts: number;
  equity: number;
}

export interface SecretField {
  set: boolean;
  hint: string;
}

export interface SettingsView {
  kalshi_env: string | null;
  series: string | null;
  start_mode: string | null;
  autostart: boolean | null;
  starting_balance: number | null;
  llm_enabled: boolean | null;
  min_edge: number | null;
  fee_buffer: number | null;
  vol_lookback_s: number | null;
  kalshi_api_key_id: SecretField;
  kalshi_private_key: SecretField;
  anthropic_api_key: SecretField;
  gemini_api_key: SecretField;
}

export interface ConnTest {
  ok: boolean;
  detail?: string;
  env?: string;
  balance_usd?: number;
}

export interface CalibrationBand {
  bucket: string;
  predicted: number;
  actual: number | null;
  count: number;
}

export interface CalibrationData {
  brier_score: number | null;
  brier_score_db: number | null;
  resolution_count: number;
  pending_count: number;
  sharpness: number;
  bands: CalibrationBand[];
}

export interface Proposal {
  id: number;
  created_at: number;
  suggested_by: string;
  description: string;
  params_json: string;
  status: "pending" | "applied" | "dismissed";
}

class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function req<T>(
  path: string,
  opts: RequestInit = {},
  auth = false
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(opts.headers as Record<string, string>),
  };
  if (auth) {
    const token = getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
  }
  const res = await fetch(`${ENGINE_URL}${path}`, { ...opts, headers });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail || detail;
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, detail);
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

export const api = {
  login: (password: string) =>
    req<{ token: string }>("/api/login", {
      method: "POST",
      body: JSON.stringify({ password }),
    }),
  health: () => req<Health>("/api/health"),
  state: () => req<EngineState>("/api/state"),
  markets: () => req<Market[]>("/api/markets"),
  trades: (limit = 100) => req<Trade[]>(`/api/trades?limit=${limit}`),
  decisions: (limit = 100) => req<Decision[]>(`/api/decisions?limit=${limit}`),
  equityCurve: () => req<EquityPoint[]>("/api/equity-curve"),
  getRisk: () => req<RiskParams>("/api/risk", {}, true),
  setRisk: (params: Partial<RiskParams>) =>
    req<RiskParams>(
      "/api/risk",
      { method: "POST", body: JSON.stringify(params) },
      true
    ),
  start: () => req<{ ok: boolean }>("/api/control/start", { method: "POST" }, true),
  stop: () => req<{ ok: boolean }>("/api/control/stop", { method: "POST" }, true),
  kill: () => req<{ ok: boolean }>("/api/control/kill", { method: "POST" }, true),
  reset: () => req<{ ok: boolean }>("/api/control/reset", { method: "POST" }, true),
  setMode: (mode: "paper" | "live") =>
    req<{ ok: boolean; mode: string }>(
      "/api/control/mode",
      { method: "POST", body: JSON.stringify({ mode }) },
      true
    ),
  getSettings: () => req<SettingsView>("/api/settings", {}, true),
  saveSettings: (payload: Record<string, any>) =>
    req<SettingsView>(
      "/api/settings",
      { method: "POST", body: JSON.stringify(payload) },
      true
    ),
  testConnection: () =>
    req<ConnTest>("/api/settings/test", { method: "POST" }, true),
  getCalibration: () => req<CalibrationData>("/api/calibration"),
  getProposals: () => req<Proposal[]>("/api/proposals", {}, true),
  applyProposal: (id: number) =>
    req<{ ok: boolean; applied_params: Record<string, number> }>(
      `/api/proposals/${id}/apply`,
      { method: "POST" },
      true
    ),
  dismissProposal: (id: number) =>
    req<{ ok: boolean }>(`/api/proposals/${id}/dismiss`, { method: "POST" }, true),
};

export { ApiError };
