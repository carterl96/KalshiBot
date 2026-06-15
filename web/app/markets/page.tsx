"use client";

import { useEffect, useState } from "react";
import { Market, api } from "@/lib/api";
import { Card, Empty } from "@/components/ui";
import { cents, countdown, pct } from "@/lib/format";

export default function MarketsPage() {
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

  return (
    <Card
      title="Live markets — Kalshi price vs model fair value"
      actions={
        <span className="text-xs text-muted">refreshing every 1s</span>
      }
    >
      {offline ? (
        <Empty>Engine offline.</Empty>
      ) : markets.length === 0 ? (
        <Empty>No active markets. Start the engine and wait for a window.</Empty>
      ) : (
        <table className="tbl">
          <thead>
            <tr>
              <th>Market</th>
              <th>Side</th>
              <th>Strike</th>
              <th>Spot</th>
              <th>Kalshi bid/ask</th>
              <th>Model</th>
              <th>Edge</th>
              <th>Closes</th>
            </tr>
          </thead>
          <tbody>
            {markets.map((m) => {
              const edge = m.edge ?? 0;
              return (
                <tr key={`${m.ticker}:${m.side}`}>
                  <td className="num">{m.ticker}</td>
                  <td className="uppercase">{m.side}</td>
                  <td className="num">{m.strike.toLocaleString()}</td>
                  <td className="num">
                    {m.spot != null ? m.spot.toLocaleString() : "—"}
                  </td>
                  <td className="num text-muted">
                    {cents(m.kalshi_bid)} / {cents(m.kalshi_ask)}
                  </td>
                  <td className="num">{pct(m.model_prob)}</td>
                  <td
                    className={`num font-semibold ${
                      edge > 0 ? "text-pos" : edge < 0 ? "text-neg" : "text-muted"
                    }`}
                  >
                    {m.edge != null ? pct(m.edge) : "—"}
                  </td>
                  <td
                    className={`num ${
                      m.time_to_close_s < 30 ? "text-paper" : "text-muted"
                    }`}
                  >
                    {countdown(m.time_to_close_s)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </Card>
  );
}
