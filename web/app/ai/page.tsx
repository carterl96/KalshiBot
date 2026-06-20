"use client";

import { useEffect, useState } from "react";
import { Decision, api } from "@/lib/api";
import { Badge, Card, Disclosure, Empty } from "@/components/ui";
import { ago, pct, signed } from "@/lib/format";

function sourceTone(source: string): "accent" | "pos" | "muted" {
  if (source === "llm") return "accent";
  if (source.includes("claude") || source.includes("gemini")) return "accent";
  return "muted";
}

// Friendly label for where a decision came from.
function sourceLabel(source: string): string {
  if (source === "llm") return "AI";
  if (source === "quant") return "Math model";
  return source;
}

function decisionTone(decision: string): "pos" | "neg" | "muted" {
  if (decision === "tradeable" || decision === "meta") return "pos";
  if (decision === "skip") return "muted";
  return "muted";
}

// Plain-language label for a decision outcome.
function decisionLabel(decision: string): string {
  switch (decision) {
    case "tradeable":
      return "Worth a bet";
    case "skip":
      return "Skipped";
    case "meta":
      return "AI review";
    default:
      return decision;
  }
}

const FILTER_OPTIONS = [
  { key: "all", label: "Everything" },
  { key: "llm", label: "AI only" },
  { key: "quant", label: "Math model only" },
] as const;
type Filter = (typeof FILTER_OPTIONS)[number]["key"];

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
      <Disclosure label="How the AI works">
        <p className="text-xs leading-relaxed text-muted">
          Every potential bet is first scored by a math model that estimates the
          odds. On top of that, an optional AI layer (Claude + Gemini) reviews
          recent performance and nudges a single &ldquo;risk dial&rdquo; up or
          down — a multiplier on bet sizes. It never places trades on its own;
          it only advises how aggressive to be. The feed below shows each call
          the bot made and why.
        </p>
      </Disclosure>

      {latestLlm && (
        <Card title="Latest AI guidance">
          <div className="flex flex-wrap items-start gap-6">
            <div>
              <div className="text-xs text-muted">
                Risk dial (bet-size multiplier)
              </div>
              <div className="mt-1 font-mono text-3xl font-semibold">
                {latestLlm.action_taken.replace("risk_dial=", "×") || "—"}
              </div>
            </div>
            <div className="flex-1">
              <div className="text-xs text-muted">Why</div>
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
                key={f.key}
                onClick={() => setFilter(f.key)}
                className={`rounded px-2 py-0.5 text-xs transition-colors ${
                  filter === f.key
                    ? "bg-accent/20 text-accent"
                    : "text-muted hover:text-text"
                }`}
              >
                {f.label}
              </button>
            ))}
          </div>
        }
      >
        {offline ? (
          <Empty>
            Can&apos;t reach the bot right now. Make sure the engine is running.
          </Empty>
        ) : visible.length === 0 ? (
          <Empty>
            Nothing here yet. As the bot evaluates markets, its decisions will
            appear in this feed.
          </Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="tbl">
              <thead>
                <tr>
                  <th>When</th>
                  <th>Decided by</th>
                  <th>Market</th>
                  <th>Call</th>
                  <th>Model %</th>
                  <th>Edge</th>
                  <th>What it did</th>
                  <th>Why</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((d) => (
                  <tr key={d.id}>
                    <td className="num text-muted">{ago(d.ts)}</td>
                    <td>
                      <Badge tone={sourceTone(d.source)}>
                        {sourceLabel(d.source)}
                      </Badge>
                    </td>
                    <td className="num">{d.ticker}</td>
                    <td>
                      <Badge tone={decisionTone(d.decision)}>
                        {decisionLabel(d.decision)}
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
