"use client";

import { useEffect, useState } from "react";
import { EngineState, Market, api } from "@/lib/api";
import { useEngine } from "@/lib/store";
import { Badge, Card, Empty } from "@/components/ui";
import { cents, countdown, pct, signed } from "@/lib/format";

function edgeBg(edge: number | null): string {
  if (edge == null) return "";
  if (edge >= 0.08) return "bg-pos/20";
  if (edge >= 0.04) return "bg-pos/8";
  if (edge < 0) return "bg-neg/8";
  return "";
}

export default function MarketsPage() {
  const { state } = useEngine();
  const [markets, setMarkets] = useState<Market[]>([]);
  const [offline, setOffline] = useState(false);

  useEffect(() => {
    const load = () =>
      api
        .markets()
        .then((m) => {
          setMarkets(m);
          setOffline(false);
        })
        .catch(() => setOffline(true));
    load();
    const id = setInterval(load, 1000);
    return () => clearInterval(id);
  }, []);

  // Build position lookup: "ticker:side" -> position
  const posMap: Record<string, NonNullable<EngineState["positions"]>[number]> = {};
  for (const p of state?.positions ?? []) {
    posMap[`${p.ticker}:${p.side}`] = p;
  }

  const tradeable = markets.filter((m) => (m.edge ?? 0) >= 0.04);
  const best = tradeable.sort((a, b) => (b.edge ?? 0) - (a.edge ?? 0))[0];

  return (
    <div className="space-y-4">
      {best && (
        <div className="flex items-center gap-3 rounded-lg border border-pos/30 bg-pos/5 px-4 py-2 text-sm">
          <span className="text-pos font-medium">Best edge:</span>
          <span className="num">{best.ticker}</span>
          <span className="uppercase text-muted">{best.side}</span>
          <span className="text-pos font-semibold">{pct(best.edge)}</span>
          <span className="text-muted">·</span>
          <span className="text-muted">{countdown(best.time_to_close_s)} to close</span>
        </div>
      )}

      <Card
        title="Live markets — Kalshi price vs model fair value"
        actions={
          <span className="text-xs text-muted">1s refresh</span>
        }
      >
        {offline ? (
          <Empty>Engine offline.</Empty>
        ) : markets.length === 0 ? (
          <Empty>No active markets. Start the engine and wait for a window.</Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="tbl">
              <thead>
                <tr>
                  <th>Market</th>
                  <th>Side</th>
                  <th>Strike</th>
                  <th>Spot</th>
                  <th>Bid / Ask</th>
                  <th>Model %</th>
                  <th>Edge</th>
                  <th>Position</th>
                  <th>Unreal.</th>
                  <th>Closes</th>
                </tr>
              </thead>
              <tbody>
                {markets.map((m) => {
                  const edge = m.edge ?? 0;
                  const pos = posMap[`${m.ticker}:${m.side}`];
                  const bg = edgeBg(m.edge);
                  return (
                    <tr key={`${m.ticker}:${m.side}`} className={bg}>
                      <td className="num font-medium">{m.ticker}</td>
                      <td>
                        <Badge tone={m.side === "up" ? "pos" : "neg"}>
                          {m.side.toUpperCase()}
                        </Badge>
                      </td>
                      <td className="num">{m.strike.toLocaleString()}</td>
                      <td className="num">
                        {m.spot != null
                          ? m.spot.toLocaleString(undefined, {
                              maximumFractionDigits: 0,
                            })
                          : "—"}
                      </td>
                      <td className="num text-muted">
                        {cents(m.kalshi_bid)}&nbsp;/&nbsp;{cents(m.kalshi_ask)}
                      </td>
                      <td className="num">
                        {m.model_prob != null ? pct(m.model_prob) : "—"}
                      </td>
                      <td
                        className={`num font-semibold ${
                          edge >= 0.04
                            ? "text-pos"
                            : edge < 0
                            ? "text-neg"
                            : "text-muted"
                        }`}
                      >
                        {m.edge != null ? signed(m.edge, 3) : "—"}
                      </td>
                      <td className="num">
                        {pos ? (
                          <span className="text-accent">
                            {pos.quantity} @ {(pos.avg_price * 100).toFixed(0)}¢
                          </span>
                        ) : (
                          <span className="text-muted">—</span>
                        )}
                      </td>
                      <td
                        className={`num ${
                          pos
                            ? pos.unrealized_pnl >= 0
                              ? "text-pos"
                              : "text-neg"
                            : "text-muted"
                        }`}
                      >
                        {pos ? signed(pos.unrealized_pnl) : "—"}
                      </td>
                      <td
                        className={`num ${
                          m.time_to_close_s < 30
                            ? "text-paper font-semibold"
                            : "text-muted"
                        }`}
                      >
                        {countdown(m.time_to_close_s)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
