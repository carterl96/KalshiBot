"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { Badge, Button, Card, Empty, Stat } from "@/components/ui";
import { pnlClass, signed } from "@/lib/format";

interface BacktestResult {
  n_trades: number;
  final_equity: number;
  total_pnl: number;
  pnl_pct: number;
  win_rate: number | null;
  brier_score: number | null;
  n_equity_points: number;
  n_predictions: number;
}

interface BacktestParams {
  starting_balance: number;
  min_edge: number;
  fee_buffer: number;
  kelly_fraction: number;
  max_per_trade: number;
  max_per_window: number;
  max_exposure: number;
  daily_loss_limit: number;
  max_drawdown_pct: number;
}

const PARAM_FIELDS: { key: keyof BacktestParams; label: string; step: string }[] = [
  { key: "starting_balance", label: "Starting balance ($)", step: "100" },
  { key: "min_edge", label: "Min edge", step: "0.01" },
  { key: "fee_buffer", label: "Fee buffer", step: "0.01" },
  { key: "kelly_fraction", label: "Kelly fraction", step: "0.05" },
  { key: "max_per_trade", label: "Max per trade ($)", step: "5" },
  { key: "max_per_window", label: "Max per window ($)", step: "10" },
  { key: "max_exposure", label: "Max exposure ($)", step: "50" },
  { key: "daily_loss_limit", label: "Daily loss limit ($)", step: "10" },
  { key: "max_drawdown_pct", label: "Max drawdown (%)", step: "1" },
];

const DEFAULT_PARAMS: BacktestParams = {
  starting_balance: 1000,
  min_edge: 0.04,
  fee_buffer: 0.02,
  kelly_fraction: 0.25,
  max_per_trade: 20,
  max_per_window: 60,
  max_exposure: 200,
  daily_loss_limit: 50,
  max_drawdown_pct: 15,
};

const SAMPLE_TICKS_PLACEHOLDER = `[
  {
    "ts": 1700000000,
    "ticker": "KXBTC-001",
    "side": "up",
    "strike": 37000,
    "spot": 37500,
    "sigma": 0.45,
    "tau": 900,
    "ask_cents": 55,
    "outcome": 1
  }
]`;

export default function BacktestPage() {
  const [params, setParams] = useState<BacktestParams>({ ...DEFAULT_PARAMS });
  const [ticksJson, setTicksJson] = useState("");
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  function setParam(key: keyof BacktestParams, val: string) {
    const num = parseFloat(val);
    if (!isNaN(num)) setParams((p) => ({ ...p, [key]: num }));
  }

  async function runBacktest() {
    setError("");
    setResult(null);
    let ticks: any[];
    try {
      ticks = JSON.parse(ticksJson || "[]");
    } catch {
      setError("Invalid JSON in ticks input.");
      return;
    }
    if (!Array.isArray(ticks) || ticks.length === 0) {
      setError("Ticks must be a non-empty JSON array.");
      return;
    }
    setBusy(true);
    try {
      const res = await (api as any).post
        ? null
        : await fetch(
            `${process.env.NEXT_PUBLIC_ENGINE_URL || "http://localhost:8000"}/api/backtest`,
            {
              method: "POST",
              headers: {
                "Content-Type": "application/json",
                Authorization: `Bearer ${typeof window !== "undefined" ? window.localStorage.getItem("kalshibot_token") : ""}`,
              },
              body: JSON.stringify({ ticks, params }),
            }
          );
      if (!res?.ok) throw new Error((await res?.json())?.detail || res?.statusText);
      setResult(await res?.json());
    } catch (e: any) {
      setError(e?.message || "Backtest failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <Card title="Backtest parameters">
        <p className="mb-4 text-xs text-muted">
          Replay historical Kalshi ticks through the pricing and risk pipeline to
          validate strategy parameters before trading live. Paste ticks as a JSON
          array (see schema below), adjust params, and click Run.
        </p>
        <div className="grid grid-cols-2 gap-4 md:grid-cols-3">
          {PARAM_FIELDS.map((f) => (
            <label key={f.key} className="block">
              <span className="text-xs text-muted">{f.label}</span>
              <input
                type="number"
                step={f.step}
                value={params[f.key]}
                onChange={(e) => setParam(f.key, e.target.value)}
                className="mt-1 w-full rounded-lg border border-line bg-bg-soft px-3 py-2 text-sm num outline-none focus:border-accent"
              />
            </label>
          ))}
        </div>
      </Card>

      <Card title="Historical ticks (JSON)">
        <p className="mb-2 text-xs text-muted">
          Each tick: <code className="text-accent">ts</code> (unix s),{" "}
          <code className="text-accent">ticker</code>,{" "}
          <code className="text-accent">side</code> (&quot;up&quot;/&quot;down&quot;),{" "}
          <code className="text-accent">strike</code>,{" "}
          <code className="text-accent">spot</code>,{" "}
          <code className="text-accent">sigma</code> (annualised vol),{" "}
          <code className="text-accent">tau</code> (seconds to close),{" "}
          <code className="text-accent">ask_cents</code> (1–99),{" "}
          <code className="text-accent">outcome</code> (1=YES won, 0=NO won)
        </p>
        <textarea
          rows={10}
          value={ticksJson}
          onChange={(e) => setTicksJson(e.target.value)}
          placeholder={SAMPLE_TICKS_PLACEHOLDER}
          className="mt-1 w-full rounded-lg border border-line bg-bg-soft px-3 py-2 font-mono text-xs outline-none focus:border-accent"
          spellCheck={false}
        />
      </Card>

      {error && (
        <div className="rounded-lg border border-neg/30 bg-neg/10 px-4 py-2 text-sm text-neg">
          {error}
        </div>
      )}

      <div>
        <Button tone="primary" onClick={runBacktest} disabled={busy}>
          {busy ? "Running…" : "▶ Run backtest"}
        </Button>
      </div>

      {result && (
        <Card title="Backtest results">
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            <Stat label="Trades" value={String(result.n_trades)} />
            <Stat
              label="Total P&L"
              value={signed(result.total_pnl)}
              className={pnlClass(result.total_pnl)}
              hint={`${result.pnl_pct >= 0 ? "+" : ""}${result.pnl_pct.toFixed(1)}%`}
            />
            <Stat
              label="Win rate"
              value={
                result.win_rate != null
                  ? `${(result.win_rate * 100).toFixed(0)}%`
                  : "—"
              }
            />
            <Stat
              label="Brier score"
              value={
                result.brier_score != null
                  ? result.brier_score.toFixed(4)
                  : "—"
              }
              hint="lower is better"
            />
            <Stat label="Final equity" value={`$${result.final_equity.toFixed(2)}`} />
            <Stat label="Predictions" value={String(result.n_predictions)} />
            <Stat label="Equity points" value={String(result.n_equity_points)} />
          </div>
        </Card>
      )}
    </div>
  );
}
