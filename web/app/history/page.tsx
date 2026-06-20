"use client";

import { useEffect, useState } from "react";
import { Trade, api } from "@/lib/api";
import { Badge, Button, Card, Empty, Select } from "@/components/ui";
import { ago, pnlClass, signed } from "@/lib/format";

// Turn raw action codes into human verbs + a badge tone.
function actionLabel(action: string): { text: string; tone: "accent" | "pos" | "muted" } {
  switch (action) {
    case "buy":
      return { text: "Bought", tone: "accent" };
    case "sell":
      return { text: "Sold", tone: "pos" };
    case "settle":
      return { text: "Settled", tone: "muted" };
    default:
      return { text: action || "—", tone: "muted" };
  }
}

function exportCsv(rows: Trade[]) {
  const headers = [
    "id", "ts", "ticker", "action", "side", "qty", "price_cents",
    "mode", "pnl", "cumulative_pnl", "reason",
  ];
  let cum = 0;
  const lines = rows
    .slice()
    .reverse()
    .map((t) => {
      cum += t.pnl ?? 0;
      return [
        t.id,
        new Date(t.ts * 1000).toISOString(),
        t.ticker,
        t.action,
        t.side,
        t.quantity,
        Math.round(t.price * 100),
        t.mode,
        (t.pnl ?? 0).toFixed(4),
        cum.toFixed(4),
        `"${(t.reason ?? "").replace(/"/g, '""')}"`,
      ].join(",");
    });
  const blob = new Blob([[headers.join(","), ...lines].join("\n")], {
    type: "text/csv",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `kalshibot_trades_${Date.now()}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

export default function HistoryPage() {
  const [rows, setRows] = useState<Trade[]>([]);
  const [offline, setOffline] = useState(false);
  const [limit, setLimit] = useState(200);

  useEffect(() => {
    const load = () =>
      api
        .trades(limit)
        .then((t) => {
          setRows(t);
          setOffline(false);
        })
        .catch(() => setOffline(true));
    load();
    const id = setInterval(load, 5000);
    return () => clearInterval(id);
  }, [limit]);

  // Compute running cumulative P&L (rows come newest-first from API).
  const withCum: (Trade & { cum_pnl: number })[] = [];
  let cum = rows.reduce((s, r) => s + (r.pnl ?? 0), 0);
  for (const row of rows) {
    withCum.push({ ...row, cum_pnl: cum });
    cum -= row.pnl ?? 0;
  }

  const totalPnl = rows.reduce((s, r) => s + (r.pnl ?? 0), 0);
  const trades = rows.filter((r) => r.action === "buy" || r.action === "sell");
  const wins = trades.filter((r) => r.pnl > 0).length;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-4 text-sm text-muted">
          <span>
            Total profit / loss:{" "}
            <span className={`font-semibold ${pnlClass(totalPnl)}`}>
              {signed(totalPnl)}
            </span>
          </span>
          {trades.length > 0 && (
            <span>
              Win rate:{" "}
              <span className="font-semibold text-text">
                {((wins / trades.length) * 100).toFixed(0)}%
              </span>{" "}
              ({wins} of {trades.length} bets won)
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <Select
            value={String(limit)}
            onChange={(v) => setLimit(Number(v))}
            className="px-2 py-1"
          >
            <option value={100}>Last 100</option>
            <option value={200}>Last 200</option>
            <option value={500}>Last 500</option>
          </Select>
          <Button onClick={() => exportCsv(rows)} disabled={rows.length === 0}>
            Download CSV
          </Button>
        </div>
      </div>

      <Card title="Trade history">
        {offline ? (
          <Empty>
            Can&apos;t reach the bot right now. Make sure the engine is running.
          </Empty>
        ) : rows.length === 0 ? (
          <Empty>
            No trades yet. Once the bot starts placing bets, they&apos;ll show
            up here.
          </Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="tbl">
              <thead>
                <tr>
                  <th>When</th>
                  <th>Market</th>
                  <th>What happened</th>
                  <th>Bet</th>
                  <th>Contracts</th>
                  <th>Price</th>
                  <th>Mode</th>
                  <th>Profit / loss</th>
                  <th>Running total</th>
                  <th>Why</th>
                </tr>
              </thead>
              <tbody>
                {withCum.map((t) => {
                  const act = actionLabel(t.action);
                  return (
                    <tr key={t.id}>
                      <td className="num text-muted">{ago(t.ts)}</td>
                      <td className="num">{t.ticker}</td>
                      <td className="text-xs">
                        <Badge tone={act.tone}>{act.text}</Badge>
                      </td>
                      <td className="text-xs capitalize">{t.side || "—"}</td>
                      <td className="num">{t.quantity || "—"}</td>
                      <td className="num">
                        {t.price ? `${(t.price * 100).toFixed(0)}¢` : "—"}
                      </td>
                      <td>
                        <Badge tone={t.mode === "live" ? "live" : "paper"}>
                          {t.mode === "live" ? "Live" : "Paper"}
                        </Badge>
                      </td>
                      <td className={`num ${pnlClass(t.pnl)}`}>
                        {t.pnl ? signed(t.pnl) : "—"}
                      </td>
                      <td className={`num ${pnlClass(t.cum_pnl)}`}>
                        {signed(t.cum_pnl)}
                      </td>
                      <td className="max-w-[180px] truncate text-xs text-muted">
                        {t.reason || "—"}
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
