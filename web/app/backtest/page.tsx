"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { Button, Card, Disclosure, Stat } from "@/components/ui";
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

const PARAM_FIELDS: {
  key: keyof BacktestParams;
  label: string;
  step: string;
  hint: string;
}[] = [
  {
    key: "starting_balance",
    label: "Starting balance ($)",
    step: "100",
    hint: "Pretend bankroll to begin with.",
  },
  {
    key: "min_edge",
    label: "Minimum edge to bet",
    step: "0.01",
    hint: "How good a deal must be before betting.",
  },
  {
    key: "fee_buffer",
    label: "Fee cushion",
    step: "0.01",
    hint: "Haircut to cover fees and spread.",
  },
  {
    key: "kelly_fraction",
    label: "Bet sizing aggressiveness",
    step: "0.05",
    hint: "0 = tiny bets, 1 = full Kelly.",
  },
  {
    key: "max_per_trade",
    label: "Most per bet ($)",
    step: "5",
    hint: "Cap on a single order.",
  },
  {
    key: "max_per_window",
    label: "Most per market ($)",
    step: "10",
    hint: "Cap per market window.",
  },
  {
    key: "max_exposure",
    label: "Most invested at once ($)",
    step: "50",
    hint: "Total open bets allowed.",
  },
  {
    key: "daily_loss_limit",
    label: "Daily stop-loss ($)",
    step: "10",
    hint: "Pause after losing this much in a day.",
  },
  {
    key: "max_drawdown_pct",
    label: "Pause if account drops by (%)",
    step: "1",
    hint: "Halt after this % drop from peak.",
  },
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
      <Card title="Test your settings on past data">
        <p className="mb-4 text-xs leading-relaxed text-muted">
          A backtest replays real historical market data through the bot so you
          can see how a set of risk settings would have performed — without
          risking any money. Adjust the settings below, paste in some past
          market data, and run it.
        </p>
        <div className="grid grid-cols-2 gap-4 md:grid-cols-3">
          {PARAM_FIELDS.map((f) => (
            <label key={f.key} className="block">
              <span className="text-xs font-medium text-text">{f.label}</span>
              <input
                type="number"
                step={f.step}
                value={params[f.key]}
                onChange={(e) => setParam(f.key, e.target.value)}
                className="mt-1 w-full rounded-lg border border-line bg-bg-soft px-3 py-2 text-sm num outline-none focus:border-accent"
              />
              <span className="mt-1 block text-[11px] leading-snug text-muted">
                {f.hint}
              </span>
            </label>
          ))}
        </div>
      </Card>

      <Card title="Past market data (JSON)">
        <p className="mb-2 text-xs text-muted">
          Paste a JSON array of market snapshots to replay. Expand below for the
          exact field reference.
        </p>
        <div className="mb-3">
          <Disclosure label="Data format reference">
            <p className="text-xs leading-relaxed text-muted">
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
          </Disclosure>
        </div>
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
        <Card title="How it would have done">
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            <Stat label="Bets placed" value={String(result.n_trades)} />
            <Stat
              label="Total profit / loss"
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
              label="Prediction accuracy"
              value={
                result.brier_score != null
                  ? (1 - result.brier_score).toFixed(3)
                  : "—"
              }
              hint="closer to 1 is better"
            />
            <Stat
              label="Ending balance"
              value={`$${result.final_equity.toFixed(2)}`}
            />
            <Stat label="Predictions graded" value={String(result.n_predictions)} />
            <Stat label="Equity points" value={String(result.n_equity_points)} />
          </div>
        </Card>
      )}
    </div>
  );
}
