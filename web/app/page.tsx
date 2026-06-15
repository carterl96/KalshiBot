"use client";

import { useEffect, useState } from "react";
import {
  Area,
  AreaChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useEngine } from "@/lib/store";
import { EquityPoint, api } from "@/lib/api";
import { Card, Empty, Stat } from "@/components/ui";
import { pnlClass, signed, ts, usd } from "@/lib/format";

export default function Dashboard() {
  const { state } = useEngine();
  const [curve, setCurve] = useState<EquityPoint[]>([]);

  useEffect(() => {
    const load = () =>
      api
        .equityCurve()
        .then((pts) =>
          setCurve(pts.map((p) => ({ ...p, t: ts(p.ts) } as any)))
        )
        .catch(() => setCurve([]));
    load();
    const id = setInterval(load, 15000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <Stat label="Equity" value={usd(state?.equity)} />
        <Stat
          label="P&L Today"
          value={signed(state?.pnl_today)}
          className={pnlClass(state?.pnl_today)}
        />
        <Stat
          label="P&L Total"
          value={signed(state?.pnl_total)}
          className={pnlClass(state?.pnl_total)}
        />
        <Stat label="Cash" value={usd(state?.balance)} />
      </div>

      <Card title="Equity curve">
        {curve.length < 2 ? (
          <Empty>No equity history yet — start the engine to begin.</Empty>
        ) : (
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={curve}>
                <defs>
                  <linearGradient id="eq" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#3b82f6" stopOpacity={0.4} />
                    <stop offset="100%" stopColor="#3b82f6" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <XAxis
                  dataKey="t"
                  tick={{ fill: "#7b8499", fontSize: 11 }}
                  minTickGap={40}
                />
                <YAxis
                  tick={{ fill: "#7b8499", fontSize: 11 }}
                  domain={["auto", "auto"]}
                  width={50}
                />
                <Tooltip
                  contentStyle={{
                    background: "#141925",
                    border: "1px solid #222a3a",
                    borderRadius: 8,
                    fontSize: 12,
                  }}
                  labelStyle={{ color: "#7b8499" }}
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
          <Empty>No open positions.</Empty>
        ) : (
          <table className="tbl">
            <thead>
              <tr>
                <th>Market</th>
                <th>Side</th>
                <th>Qty</th>
                <th>Avg</th>
                <th>Mark</th>
                <th>Unrealized</th>
              </tr>
            </thead>
            <tbody>
              {state.positions.map((p) => (
                <tr key={`${p.ticker}:${p.side}`}>
                  <td className="num">{p.ticker}</td>
                  <td className="uppercase">{p.side}</td>
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
        )}
      </Card>
    </div>
  );
}
