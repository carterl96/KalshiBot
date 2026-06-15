"use client";

import { useEffect, useState } from "react";
import { Decision, api } from "@/lib/api";
import { Badge, Card, Empty } from "@/components/ui";
import { pct, ts } from "@/lib/format";

export default function AiLogPage() {
  const [rows, setRows] = useState<Decision[]>([]);
  const [offline, setOffline] = useState(false);

  useEffect(() => {
    const load = () =>
      api
        .decisions(200)
        .then((d) => {
          setRows(d);
          setOffline(false);
        })
        .catch(() => setOffline(true));
    load();
    const id = setInterval(load, 4000);
    return () => clearInterval(id);
  }, []);

  return (
    <Card title="Decision & AI log">
      {offline ? (
        <Empty>Engine offline.</Empty>
      ) : rows.length === 0 ? (
        <Empty>No decisions logged yet.</Empty>
      ) : (
        <table className="tbl">
          <thead>
            <tr>
              <th>Time</th>
              <th>Source</th>
              <th>Market</th>
              <th>Decision</th>
              <th>Model</th>
              <th>Edge</th>
              <th>Action</th>
              <th>Detail</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((d) => (
              <tr key={d.id}>
                <td className="num text-muted">{ts(d.ts)}</td>
                <td>
                  <Badge tone={d.source === "llm" ? "accent" : "muted"}>
                    {d.source}
                  </Badge>
                </td>
                <td className="num">{d.ticker}</td>
                <td>{d.decision}</td>
                <td className="num">{d.model_prob ? pct(d.model_prob) : "—"}</td>
                <td
                  className={`num ${
                    d.edge > 0 ? "text-pos" : d.edge < 0 ? "text-neg" : "text-muted"
                  }`}
                >
                  {d.edge ? pct(d.edge) : "—"}
                </td>
                <td className="text-muted">{d.action_taken || "—"}</td>
                <td className="text-muted">{d.detail}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}
