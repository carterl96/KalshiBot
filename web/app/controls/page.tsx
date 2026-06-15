"use client";

import { useEffect, useState } from "react";
import { RiskParams, api } from "@/lib/api";
import { useEngine } from "@/lib/store";
import { Badge, Button, Card } from "@/components/ui";

const RISK_FIELDS: { key: keyof RiskParams; label: string; hint: string }[] = [
  { key: "max_per_trade", label: "Max per trade ($)", hint: "single order cap" },
  { key: "max_per_window", label: "Max per window ($)", hint: "per market" },
  { key: "max_exposure", label: "Max exposure ($)", hint: "total open" },
  { key: "daily_loss_limit", label: "Daily loss limit ($)", hint: "halts entries" },
  { key: "max_drawdown_pct", label: "Max drawdown (%)", hint: "circuit breaker" },
  { key: "kelly_fraction", label: "Kelly fraction", hint: "0–1 sizing" },
];

export default function ControlsPage() {
  const { state, refresh } = useEngine();
  const [risk, setRisk] = useState<RiskParams | null>(null);
  const [msg, setMsg] = useState("");
  const [confirmLive, setConfirmLive] = useState(false);

  useEffect(() => {
    api.getRisk().then(setRisk).catch(() => setRisk(null));
  }, []);

  async function act(fn: () => Promise<any>, label: string) {
    try {
      await fn();
      setMsg(`${label} ✓`);
      refresh();
    } catch (e: any) {
      setMsg(`${label}: ${e?.message || "failed"}`);
    }
  }

  async function saveRisk() {
    if (!risk) return;
    try {
      const updated = await api.setRisk(risk);
      setRisk(updated);
      setMsg("Risk parameters saved ✓");
    } catch (e: any) {
      setMsg(`Save failed: ${e?.message}`);
    }
  }

  async function toggleMode() {
    if (!state) return;
    if (state.mode === "paper") {
      setConfirmLive(true);
      return;
    }
    await act(() => api.setMode("paper"), "Switched to paper");
  }

  async function confirmGoLive() {
    setConfirmLive(false);
    await act(() => api.setMode("live"), "Switched to LIVE");
  }

  return (
    <div className="space-y-6">
      {msg && (
        <div className="rounded-lg border border-line bg-bg-card px-4 py-2 text-sm text-muted">
          {msg}
        </div>
      )}

      <Card title="Engine">
        <div className="flex flex-wrap items-center gap-3">
          <Button tone="primary" onClick={() => act(api.start, "Started")}>
            ▶ Start
          </Button>
          <Button onClick={() => act(api.stop, "Stopped")}>■ Stop</Button>
          <Button onClick={() => act(api.reset, "Reset breakers")}>
            ↺ Reset breakers
          </Button>
          <div className="ml-auto flex items-center gap-2">
            {state?.circuit_broken && <Badge tone="neg">CIRCUIT BROKEN</Badge>}
            {state?.kill_switched && <Badge tone="neg">KILLED</Badge>}
            <Badge tone={state?.running ? "pos" : "muted"}>
              {state?.running ? "running" : "stopped"}
            </Badge>
          </div>
        </div>
      </Card>

      <Card title="Trading mode">
        <div className="flex items-center gap-4">
          <Badge tone={state?.mode === "live" ? "live" : "paper"}>
            {(state?.mode ?? "paper").toUpperCase()}
          </Badge>
          <Button
            tone={state?.mode === "paper" ? "danger" : "default"}
            onClick={toggleMode}
          >
            {state?.mode === "paper" ? "Enable LIVE trading" : "Back to paper"}
          </Button>
          <span className="text-xs text-muted">
            Live trades real money — hard caps still apply.
          </span>
        </div>
      </Card>

      <Card title="Kill switch">
        <div className="flex items-center gap-4">
          <Button tone="danger" onClick={() => act(api.kill, "KILL engaged")}>
            ⛔ KILL — flatten & halt
          </Button>
          <span className="text-xs text-muted">
            Immediately closes all positions and blocks new entries until reset.
          </span>
        </div>
      </Card>

      <Card title="Risk parameters">
        {!risk ? (
          <div className="text-sm text-muted">
            Sign-in required to view risk parameters (or engine offline).
          </div>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-4 md:grid-cols-3">
              {RISK_FIELDS.map((f) => (
                <label key={f.key} className="block">
                  <span className="text-xs text-muted">{f.label}</span>
                  <input
                    type="number"
                    step="0.01"
                    value={risk[f.key]}
                    onChange={(e) =>
                      setRisk({ ...risk, [f.key]: parseFloat(e.target.value) })
                    }
                    className="mt-1 w-full rounded-lg border border-line bg-bg-soft px-3 py-2 text-sm num outline-none focus:border-accent"
                  />
                  <span className="text-[10px] text-muted">{f.hint}</span>
                </label>
              ))}
            </div>
            <div className="mt-4">
              <Button tone="primary" onClick={saveRisk}>
                Save risk parameters
              </Button>
            </div>
          </>
        )}
      </Card>

      {confirmLive && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
          <div className="w-96 rounded-2xl border border-live bg-bg-card p-6">
            <h3 className="mb-2 text-lg font-semibold text-live">
              Enable LIVE trading?
            </h3>
            <p className="mb-5 text-sm text-muted">
              The engine will place orders with <strong>real money</strong> on
              Kalshi. Hard risk caps still apply, but losses are real. Continue?
            </p>
            <div className="flex justify-end gap-2">
              <Button onClick={() => setConfirmLive(false)}>Cancel</Button>
              <Button tone="danger" onClick={confirmGoLive}>
                Yes, go live
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
