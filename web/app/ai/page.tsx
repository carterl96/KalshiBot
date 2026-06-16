"use client";

import { useEffect, useState } from "react";
import { Decision, api } from "@/lib/api";
import { Badge, Card, Empty } from "@/components/ui";
import { ago, pct, signed } from "@/lib/format";

function sourceTone(source: string): "accent" | "pos" | "muted" {
  if (source === "llm") return "accent";
  if (source.includes("claude") || source.includes("gemini")) return "accent";
  return "muted";
}

function decisionTone(decision: string): "pos" | "neg" | "muted" {
  if (decision === "tradeable" || decision === "meta") return "pos";
  if (decision === "skip") return "muted";
  return "muted";
}

const FILTER_OPTIONS = ["all", "llm", "quant"] as const;
type Filter = (typeof FILTER_OPTIONS)[number];

export default function AiLogPage() {
  const [rows, setRows] = useState<Decision[]>([]);
  const [offline, setOffline] = useState(false);
  const [filter, setFilter] = useState<Filter>("all");

  useEffect(() => {
    const load = () =>
      api
        .decisions(300)
        .then((d) => {
          setRows(d);
          setOffline(false);
        })
        .catch(() => setOffline(true));
    load();
    const id = setInterval(load, 4000);
    return () => clearInterval(id);
  }, []);

  const visible =
    filter === "all" ? rows : rows.filter((r) => r.source === filter);

  const llmRows = rows.filter((r) => r.source === "llm");
  const latestLlm = llmRows[0];

  return (
    <div className="space-y-6">
      {latestLlm && (
        <Card title="Latest AI guidance">
          <div className="flex flex-wrap items-start gap-6">
            <div>
              <div className="text-xs text-muted">Risk dial</div>
              <div className="mt-1 font-mono text-3xl font-semibold">
                {latestLlm.action_taken.replace("risk_dial=", "×") || "—"}
              </div>
            </div>
            <div className="flex-1">
              <div className="text-xs text-muted">Note</div>
              <p className="mt-1 text-sm">{latestLlm.detail || "—"}</p>
            </div>
            <div className="text-right text-xs text-muted">
              {ago(latestLlm.ts)}
            </div>
          </div>
        </Card>
      )}

      <Card
        title="Decision feed"
        actions={
          <div className="flex gap-1">
            {FILTER_OPTIONS.map((f) => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={`rounded px-2 py-0.5 text-xs transition-colors ${
                  filter === f
                    ? "bg-accent/20 text-accent"
                    : "text-muted hover:text-text"
                }`}
              >
                {f}
              </button>
            ))}
          </div>
        }
      >
        {offline ? (
          <Empty>Engine offline.</Empty>
        ) : visible.length === 0 ? (
          <Empty>No decisions logged yet.</Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="tbl">
              <thead>
                <tr>
                  <th>When</th>
                  <th>Source</th>
                  <th>Market</th>
                  <th>Decision</th>
                  <th>Model %</th>
                  <th>Edge</th>
                  <th>Action</th>
                  <th>Detail</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((d) => (
                  <tr key={d.id}>
                    <td className="num text-muted">{ago(d.ts)}</td>
                    <td>
                      <Badge tone={sourceTone(d.source)}>{d.source}</Badge>
                    </td>
                    <td className="num">{d.ticker}</td>
                    <td>
                      <Badge tone={decisionTone(d.decision)}>
                        {d.decision}
                      </Badge>
                    </td>
                    <td className="num">
                      {d.model_prob ? pct(d.model_prob) : "—"}
                    </td>
                    <td
                      className={`num ${
                        d.edge > 0
                          ? "text-pos"
                          : d.edge < 0
                          ? "text-neg"
                          : "text-muted"
                      }`}
                    >
                      {d.edge ? signed(d.edge, 3) : "—"}
                    </td>
                    <td className="max-w-[160px] truncate text-xs text-muted">
                      {d.action_taken || "—"}
                    </td>
                    <td className="max-w-[200px] truncate text-xs text-muted">
                      {d.detail}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
