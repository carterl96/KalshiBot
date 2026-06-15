"use client";

import { useEffect, useState } from "react";
import { Trade, api } from "@/lib/api";
import { Badge, Card, Empty } from "@/components/ui";
import { pnlClass, signed, ts } from "@/lib/format";

export default function HistoryPage() {
  const [rows, setRows] = useState<Trade[]>([]);
  const [offline, setOffline] = useState(false);

  useEffect(() => {
    const load = () =>
      api
        .trades(200)
        .then((t) => {
          setRows(t);
          setOffline(false);
        })
        .catch(() => setOffline(true));
    load();
    const id = setInterval(load, 4000);
    return () => clearInterval(id);
  }, []);

  return (
    <Card title="Trade history">
      {offline ? (
        <Empty>Engine offline.</Empty>
      ) : rows.length === 0 ? (
        <Empty>No trades yet.</Empty>
      ) : (
        <table className="tbl">
          <thead>
            <tr>
              <th>Time</th>
              <th>Market</th>
              <th>Action</th>
              <th>Side</th>
              <th>Qty</th>
              <th>Price</th>
              <th>Mode</th>
              <th>P&L</th>
              <th>Reason</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((t) => (
              <tr key={t.id}>
                <td className="num text-muted">{ts(t.ts)}</td>
                <td className="num">{t.ticker}</td>
                <td className="uppercase">{t.action}</td>
                <td className="uppercase">{t.side}</td>
                <td className="num">{t.quantity || "—"}</td>
                <td className="num">
                  {t.price ? `${(t.price * 100).toFixed(0)}¢` : "—"}
                </td>
                <td>
                  <Badge tone={t.mode === "live" ? "live" : "paper"}>
                    {t.mode}
                  </Badge>
                </td>
                <td className={`num ${pnlClass(t.pnl)}`}>
                  {t.pnl ? signed(t.pnl) : "—"}
                </td>
                <td className="text-muted">{t.reason}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}
