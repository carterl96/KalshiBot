"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useEngine } from "@/lib/store";
import { CalibrationData, EquityPoint, api } from "@/lib/api";
import { Card, Empty, Stat } from "@/components/ui";
import { pnlClass, signed, usd } from "@/lib/format";

type RangeKey = "24H" | "7D" | "30D" | "ALL";
const RANGES: { key: RangeKey; label: string; seconds: number }[] = [
  { key: "24H", label: "24h", seconds: 86400 },
  { key: "7D", label: "7 days", seconds: 7 * 86400 },
  { key: "30D", label: "30 days", seconds: 30 * 86400 },
  { key: "ALL", label: "All time", seconds: Infinity },
];

function fmtAxis(tsSeconds: number, range: RangeKey): string {
  const d = new Date(tsSeconds * 1000);
  if (range === "24H")
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  return d.toLocaleDateString([], { month: "short", day: "numeric" });
}

function RangeToggle({
  value,
  onChange,
}: {
  value: RangeKey;
  onChange: (k: RangeKey) => void;
}) {
  return (
    <div className="flex rounded-lg border border-line bg-bg-soft p-0.5">
      {RANGES.map((r) => (
        <button
          key={r.key}
          onClick={() => onChange(r.key)}
          className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
            value === r.key
              ? "bg-bg-hover text-text"
              : "text-muted hover:text-text"
          }`}
        >
          {r.label}
        </button>
      ))}
    </div>
  );
}

function AdvancedMetrics({ cal }: { cal: CalibrationData | null }) {
  const [open, setOpen] = useState(false);
  if (!cal) return null;
  const brier = cal.brier_score ?? cal.brier_score_db;
  return (
    <Card>
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between text-left"
      >
        <span className="text-sm font-medium text-muted">
          Advanced: model accuracy
        </span>
        <span className="text-muted">{open ? "▲" : "▼"}</span>
      </button>
      {open && (
        <div className="mt-4 space-y-4">
          <p className="text-xs text-muted">
            How well the bot&apos;s probability predictions matched reality. Used
            to gauge whether the strategy&apos;s &ldquo;edge&rdquo; is real.
          </p>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <Stat
              label="Prediction accuracy"
              value={brier != null ? (1 - brier).toFixed(3) : "—"}
              hint="closer to 1 is better (Brier-based)"
            />
            <Stat
              label="Resolved bets"
              value={String(cal.resolution_count)}
              hint="how many predictions we can grade"
            />
            <Stat
              label="Confidence"
              value={`${(cal.sharpness * 100).toFixed(0)}%`}
              hint="how often the bot took a strong view"
            />
          </div>
          {cal.bands.some((b) => b.count > 0) && (
            <div className="overflow-x-auto">
              <table className="tbl">
                <thead>
                  <tr>
                    <th>Predicted range</th>
                    <th>Predicted</th>
                    <th>Actual</th>
                    <th>Count</th>
                  </tr>
                </thead>
                <tbody>
                  {cal.bands
                    .filter((b) => b.count > 0)
                    .map((b) => {
                      const diff =
                        b.actual != null ? b.actual - b.predicted : null;
                      return (
                        <tr key={b.bucket}>
                          <td className="num">{b.bucket}</td>
                          <td className="num">
                            {(b.predicted * 100).toFixed(0)}%
                          </td>
                          <td
                            className={`num ${
                              diff == null
                                ? ""
                                : Math.abs(diff) < 0.05
                                ? "text-pos"
                                : "text-neg"
                            }`}
                          >
                            {b.actual != null
                              ? `${(b.actual * 100).toFixed(1)}%`
                              : "—"}
                          </td>
                          <td className="num">{b.count}</td>
                        </tr>
                      );
                    })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}

export default function Dashboard() {
  const { state } = useEngine();
  const [curve, setCurve] = useState<EquityPoint[]>([]);
  const [cal, setCal] = useState<CalibrationData | null>(null);
  const [range, setRange] = useState<RangeKey>("24H");

  useEffect(() => {
    const load = () =>
      api
        .equityCurve()
        .then((pts) => setCurve(pts))
        .catch(() => setCurve([]));
    load();
    const id = setInterval(load, 15000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    const load = () => api.getCalibration().then(setCal).catch(() => {});
    load();
    const id = setInterval(load, 30000);
    return () => clearInterval(id);
  }, []);

  // Filter the curve to the selected range and compute P&L over that window.
  const { chartData, rangePnl, rangePct } = useMemo(() => {
    const r = RANGES.find((x) => x.key === range)!;
    const now = Date.now() / 1000;
    const cutoff = r.seconds === Infinity ? 0 : now - r.seconds;
    const inRange = curve.filter((p) => p.ts >= cutoff);
    const pts = inRange.length >= 2 ? inRange : curve;
    const data = pts.map((p) => ({
      ...p,
      t: fmtAxis(p.ts, range),
    }));
    let pnl: number | null = null;
    let pct: number | null = null;
    if (pts.length >= 2) {
      const first = pts[0].equity;
      const last = pts[pts.length - 1].equity;
      pnl = last - first;
      pct = first !== 0 ? (last - first) / first : null;
    } else if (range === "ALL") {
      pnl = state?.pnl_total ?? null;
    }
    return { chartData: data, rangePnl: pnl, rangePct: pct };
  }, [curve, range, state?.pnl_total]);

  return (
    <div className="space-y-5">
      {/* Hero: account value + period P&L */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card className="sm:col-span-2">
          <div className="text-xs uppercase tracking-wide text-muted">
            Account value
          </div>
          <div className="mt-1 font-mono text-4xl font-semibold">
            {usd(state?.equity)}
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
            <span className="text-muted">
              Cash{" "}
              <span className="num text-text">{usd(state?.balance)}</span>
            </span>
            <span className="text-muted">
              Today{" "}
              <span className={`num ${pnlClass(state?.pnl_today)}`}>
                {signed(state?.pnl_today)}
              </span>
            </span>
            <span className="text-muted">
              All time{" "}
              <span className={`num ${pnlClass(state?.pnl_total)}`}>
                {signed(state?.pnl_total)}
              </span>
            </span>
          </div>
        </Card>
        <Stat
          label={`Profit / loss · ${
            RANGES.find((r) => r.key === range)!.label
          }`}
          value={signed(rangePnl)}
          hint={
            rangePct != null
              ? `${rangePct >= 0 ? "+" : ""}${(rangePct * 100).toFixed(2)}%`
              : "not enough history yet"
          }
          className={pnlClass(rangePnl)}
        />
        <Stat
          label="Open positions"
          value={String(state?.positions.length ?? 0)}
          hint={state?.circuit_broken ? "⚠ trading paused (drawdown)" : "active bets"}
          className={state?.circuit_broken ? "text-neg" : ""}
        />
      </div>

      <Card
        title="Account value over time"
        actions={<RangeToggle value={range} onChange={setRange} />}
      >
        {chartData.length < 2 ? (
          <Empty>
            No history yet — start the engine to begin tracking your balance.
          </Empty>
        ) : (
          <div className="h-64 sm:h-72">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart
                data={chartData}
                margin={{ top: 5, right: 8, bottom: 0, left: 0 }}
              >
                <defs>
                  <linearGradient id="eq" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#3b82f6" stopOpacity={0.35} />
                    <stop offset="100%" stopColor="#3b82f6" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="#1a2031" vertical={false} />
                <XAxis
                  dataKey="t"
                  tick={{ fill: "#7b8499", fontSize: 11 }}
                  minTickGap={48}
                  tickLine={false}
                  axisLine={{ stroke: "#222a3a" }}
                />
                <YAxis
                  tick={{ fill: "#7b8499", fontSize: 11 }}
                  domain={["auto", "auto"]}
                  width={52}
                  tickLine={false}
                  axisLine={false}
                  tickFormatter={(v) => `$${Number(v).toFixed(0)}`}
                />
                <Tooltip
                  contentStyle={{
                    background: "#141925",
                    border: "1px solid #222a3a",
                    borderRadius: 8,
                    fontSize: 12,
                  }}
                  labelStyle={{ color: "#7b8499" }}
                  formatter={(v: number) => [usd(v), "Account value"]}
                />
                <Area
                  type="monotone"
                  dataKey="equity"
                  stroke="#3b82f6"
                  strokeWidth={2}
                  fill="url(#eq)"
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        )}
      </Card>

      <Card title="Open positions">
        {!state || state.positions.length === 0 ? (
          <Empty>No open positions right now.</Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="tbl">
              <thead>
                <tr>
                  <th>Market</th>
                  <th>Bet</th>
                  <th>Contracts</th>
                  <th>Avg cost</th>
                  <th>Now</th>
                  <th>Profit / loss</th>
                </tr>
              </thead>
              <tbody>
                {state.positions.map((p) => (
                  <tr key={`${p.ticker}:${p.side}`}>
                    <td className="num">{p.ticker}</td>
                    <td className="uppercase">{p.side === "up" ? "Up" : "Down"}</td>
                    <td className="num">{p.quantity}</td>
                    <td className="num">{(p.avg_price * 100).toFixed(0)}¢</td>
                    <td className="num">{(p.current_price * 100).toFixed(0)}¢</td>
                    <td className={`num ${pnlClass(p.unrealized_pnl)}`}>
                      {signed(p.unrealized_pnl)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <AdvancedMetrics cal={cal} />
    </div>
  );
}
