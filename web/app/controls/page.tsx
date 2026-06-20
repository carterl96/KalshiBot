"use client";

import { useEffect, useState } from "react";
import { Proposal, RiskParams, api } from "@/lib/api";
import { useEngine } from "@/lib/store";
import { Badge, Button, Disclosure, Empty, Section } from "@/components/ui";
import { ago } from "@/lib/format";

// Plain-language labels + everyday hints for the underlying risk parameters.
const RISK_FIELDS: {
  key: keyof RiskParams;
  label: string;
  hint: string;
  step: string;
}[] = [
  {
    key: "max_per_trade",
    label: "Most to risk on one bet",
    hint: "The biggest single order the bot will place.",
    step: "1",
  },
  {
    key: "max_per_window",
    label: "Most to risk per market",
    hint: "Cap on everything spent in one market window.",
    step: "1",
  },
  {
    key: "max_exposure",
    label: "Most invested at once",
    hint: "Total money allowed in open bets at any time.",
    step: "10",
  },
  {
    key: "daily_loss_limit",
    label: "Stop after losing (per day)",
    hint: "Pause new bets once losses hit this much in a day.",
    step: "5",
  },
  {
    key: "max_drawdown_pct",
    label: "Pause if account drops by",
    hint: "Halt trading after this % drop from the peak.",
    step: "1",
  },
  {
    key: "kelly_fraction",
    label: "Bet sizing aggressiveness",
    hint: "0 = tiny bets, 1 = full Kelly. Higher means bigger bets.",
    step: "0.05",
  },
];

// Risk presets. Balanced ≈ the engine defaults.
type PresetKey = "conservative" | "balanced" | "aggressive";
const PRESETS: {
  key: PresetKey;
  name: string;
  blurb: string;
  values: RiskParams;
}[] = [
  {
    key: "conservative",
    name: "Conservative",
    blurb: "Smaller bets, exits losses sooner. Lower risk, steadier ride.",
    values: {
      max_per_trade: 10,
      max_per_window: 30,
      max_exposure: 100,
      daily_loss_limit: 25,
      max_drawdown_pct: 8,
      kelly_fraction: 0.15,
    },
  },
  {
    key: "balanced",
    name: "Balanced",
    blurb: "A sensible middle ground — the recommended starting point.",
    values: {
      max_per_trade: 20,
      max_per_window: 60,
      max_exposure: 200,
      daily_loss_limit: 50,
      max_drawdown_pct: 15,
      kelly_fraction: 0.25,
    },
  },
  {
    key: "aggressive",
    name: "Aggressive",
    blurb: "Bigger bets, more room to ride drawdowns. Higher risk and reward.",
    values: {
      max_per_trade: 40,
      max_per_window: 120,
      max_exposure: 400,
      daily_loss_limit: 100,
      max_drawdown_pct: 25,
      kelly_fraction: 0.4,
    },
  },
];

// Detect which preset (if any) the current params exactly match.
function matchPreset(risk: RiskParams | null): PresetKey | null {
  if (!risk) return null;
  for (const p of PRESETS) {
    const same = (Object.keys(p.values) as (keyof RiskParams)[]).every(
      (k) => Math.abs(p.values[k] - risk[k]) < 1e-9
    );
    if (same) return p.key;
  }
  return null;
}

export default function ControlsPage() {
  const { state, refresh } = useEngine();
  const [risk, setRisk] = useState<RiskParams | null>(null);
  const [msg, setMsg] = useState("");
  const [confirmLive, setConfirmLive] = useState(false);
  const [proposals, setProposals] = useState<Proposal[]>([]);

  useEffect(() => {
    const load = () =>
      api
        .getProposals()
        .then(setProposals)
        .catch(() => {});
    load();
    const id = setInterval(load, 30000);
    return () => clearInterval(id);
  }, []);

  async function handleProposal(id: number, action: "apply" | "dismiss") {
    try {
      if (action === "apply") {
        const result = await api.applyProposal(id);
        const keys = Object.keys(result.applied_params).join(", ");
        setMsg(`Proposal applied — updated: ${keys} ✓`);
        api.getRisk().then(setRisk).catch(() => {});
      } else {
        await api.dismissProposal(id);
        setMsg("Proposal dismissed.");
      }
      api.getProposals().then(setProposals).catch(() => {});
      refresh();
    } catch (e: any) {
      setMsg(`Failed: ${e?.message}`);
    }
  }

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

  // Selecting a preset just pre-fills the form; saving still calls api.setRisk().
  function applyPreset(p: (typeof PRESETS)[number]) {
    setRisk({ ...p.values });
    setMsg(`${p.name} preset loaded — review and save to apply.`);
  }

  async function saveRisk() {
    if (!risk) return;
    try {
      const updated = await api.setRisk(risk);
      setRisk(updated);
      setMsg("Risk settings saved ✓");
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

  const activePreset = matchPreset(risk);

  return (
    <div className="space-y-5">
      {msg && (
        <div className="rounded-lg border border-line bg-bg-card px-4 py-2 text-sm text-muted">
          {msg}
        </div>
      )}

      <Section
        title="Engine"
        description="Start or stop the bot. Reset clears any safety pauses (circuit breakers) so trading can resume."
        actions={
          <div className="flex items-center gap-2">
            {state?.circuit_broken && <Badge tone="neg">Paused (drawdown)</Badge>}
            {state?.kill_switched && <Badge tone="neg">Killed</Badge>}
            <Badge tone={state?.running ? "pos" : "muted"}>
              {state?.running ? "Running" : "Stopped"}
            </Badge>
          </div>
        }
      >
        <div className="flex flex-wrap items-center gap-3">
          <Button tone="primary" onClick={() => act(api.start, "Started")}>
            ▶ Start bot
          </Button>
          <Button onClick={() => act(api.stop, "Stopped")}>■ Stop bot</Button>
          <Button onClick={() => act(api.reset, "Reset breakers")}>
            ↺ Resume after pause
          </Button>
        </div>
      </Section>

      <Section
        title="Trading mode"
        description={
          <>
            <strong className="text-text">Paper</strong> trades with pretend
            money so you can test safely.{" "}
            <strong className="text-text">Live</strong> places real orders on
            Kalshi with real money. Your risk limits apply either way.
          </>
        }
        actions={
          <Badge tone={state?.mode === "live" ? "live" : "paper"}>
            {state?.mode === "live" ? "Live money" : "Practice (paper)"}
          </Badge>
        }
      >
        <Button
          tone={state?.mode === "paper" ? "danger" : "default"}
          onClick={toggleMode}
        >
          {state?.mode === "paper"
            ? "Switch to live trading"
            : "Switch back to paper"}
        </Button>
      </Section>

      <Section
        title="Emergency stop"
        description="Instantly sells every open position and blocks new bets until you resume the engine. Use this if something looks wrong."
      >
        <Button tone="danger" onClick={() => act(api.kill, "Emergency stop engaged")}>
          ⛔ Sell everything &amp; halt
        </Button>
      </Section>

      <Section
        title="Risk level"
        description="Pick how aggressively the bot bets. Each preset fills in sensible limits — you can fine-tune them under Advanced settings below before saving."
      >
        {!risk ? (
          <div className="text-sm text-muted">
            Sign in to view your risk settings (or the engine is offline).
          </div>
        ) : (
          <>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              {PRESETS.map((p) => {
                const selected = activePreset === p.key;
                return (
                  <button
                    key={p.key}
                    onClick={() => applyPreset(p)}
                    className={`rounded-xl border p-4 text-left transition-colors ${
                      selected
                        ? "border-accent bg-accent/10"
                        : "border-line bg-bg-soft hover:bg-bg-hover"
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-sm font-semibold text-text">
                        {p.name}
                      </span>
                      {selected && <Badge tone="accent">Selected</Badge>}
                    </div>
                    <p className="mt-1.5 text-xs leading-relaxed text-muted">
                      {p.blurb}
                    </p>
                  </button>
                );
              })}
            </div>
            {activePreset == null && (
              <p className="mt-3 text-xs text-muted">
                Custom settings — these don&apos;t match a preset.
              </p>
            )}

            <div className="mt-4">
              <Disclosure
                label="Advanced settings"
                hint="exact dollar limits and sizing"
              >
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
                  {RISK_FIELDS.map((f) => (
                    <label key={f.key} className="block">
                      <span className="text-xs font-medium text-text">
                        {f.label}
                      </span>
                      <input
                        type="number"
                        step={f.step}
                        value={risk[f.key]}
                        onChange={(e) =>
                          setRisk({
                            ...risk,
                            [f.key]: parseFloat(e.target.value),
                          })
                        }
                        className="mt-1 w-full rounded-lg border border-line bg-bg-soft px-3 py-2 text-sm num outline-none focus:border-accent"
                      />
                      <span className="mt-1 block text-[11px] leading-snug text-muted">
                        {f.hint}
                      </span>
                    </label>
                  ))}
                </div>
              </Disclosure>
            </div>

            <div className="mt-4">
              <Button tone="primary" onClick={saveRisk}>
                Save risk settings
              </Button>
            </div>
          </>
        )}
      </Section>

      <Section
        title="AI suggestions"
        description="After enough bets settle, the AI layer may suggest tweaks to your risk settings. Review each one and apply it if you agree."
      >
        {proposals.length === 0 ? (
          <Empty>
            No suggestions yet — they appear here once the AI has reviewed
            enough completed trades.
          </Empty>
        ) : (
          <div className="space-y-3">
            {proposals.map((p) => {
              let params: Record<string, number> = {};
              try {
                params = JSON.parse(p.params_json);
              } catch {
                /* ignore */
              }
              return (
                <div
                  key={p.id}
                  className={`rounded-lg border p-4 ${
                    p.status === "pending"
                      ? "border-accent/30 bg-accent/5"
                      : "border-line bg-bg-soft opacity-60"
                  }`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex-1">
                      <p className="text-sm">{p.description}</p>
                      <div className="mt-2 flex flex-wrap gap-2">
                        {Object.entries(params).map(([k, v]) => (
                          <span
                            key={k}
                            className="rounded bg-bg-hover px-2 py-0.5 font-mono text-xs"
                          >
                            {k}: {typeof v === "number" ? v.toFixed(4) : String(v)}
                          </span>
                        ))}
                      </div>
                      <div className="mt-1 flex items-center gap-2 text-[10px] text-muted">
                        <span>{ago(p.created_at)}</span>
                        <span>·</span>
                        <span>{p.suggested_by}</span>
                        {p.status !== "pending" && (
                          <>
                            <span>·</span>
                            <Badge
                              tone={p.status === "applied" ? "pos" : "muted"}
                            >
                              {p.status}
                            </Badge>
                          </>
                        )}
                      </div>
                    </div>
                    {p.status === "pending" && (
                      <div className="flex gap-2">
                        <Button
                          tone="primary"
                          onClick={() => handleProposal(p.id, "apply")}
                        >
                          Apply
                        </Button>
                        <Button
                          tone="ghost"
                          onClick={() => handleProposal(p.id, "dismiss")}
                        >
                          Dismiss
                        </Button>
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </Section>

      {confirmLive && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div className="w-96 rounded-2xl border border-live bg-bg-card p-6">
            <h3 className="mb-2 text-lg font-semibold text-live">
              Switch to live trading?
            </h3>
            <p className="mb-5 text-sm text-muted">
              The bot will start placing orders with <strong>real money</strong>{" "}
              on Kalshi. Your risk limits still apply, but any losses are real.
              Are you sure?
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
