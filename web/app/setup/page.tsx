"use client";

import { useEffect, useState } from "react";
import { ConnTest, SecretField, SettingsView, api } from "@/lib/api";
import { Badge, Button, Card } from "@/components/ui";

// Local form model: secrets are entered as plain strings (empty = keep current).
type Form = {
  kalshi_env: string;
  series: string;
  start_mode: string;
  autostart: boolean;
  starting_balance: string;
  llm_enabled: boolean;
  min_edge: string;
  fee_buffer: string;
  vol_lookback_s: string;
  alert_equity_drop_pct: string;
  kalshi_api_key_id: string;
  kalshi_private_key: string;
  anthropic_api_key: string;
  gemini_api_key: string;
  alert_webhook_url: string;
};

const SECRET_KEYS = [
  "kalshi_api_key_id",
  "kalshi_private_key",
  "anthropic_api_key",
  "gemini_api_key",
  "alert_webhook_url",
] as const;

const input =
  "mt-1 w-full rounded-lg border border-line bg-bg-soft px-3 py-2 text-sm outline-none focus:border-accent";

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="text-xs text-muted">{label}</span>
      {children}
      {hint && <span className="text-[10px] text-muted">{hint}</span>}
    </label>
  );
}

function SecretInput({
  label,
  meta,
  value,
  onChange,
  onClear,
  placeholder,
}: {
  label: string;
  meta: SecretField | undefined;
  value: string;
  onChange: (v: string) => void;
  onClear: () => void;
  placeholder?: string;
}) {
  return (
    <Field
      label={label}
      hint={
        meta?.set
          ? `Currently set (${meta.hint}). Leave blank to keep.`
          : placeholder || "Not set."
      }
    >
      <div className="flex items-center gap-2">
        <input
          type="password"
          autoComplete="new-password"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={meta?.set ? "•••• keep current" : "enter value"}
          className={input}
        />
        {meta?.set && (
          <button
            type="button"
            onClick={onClear}
            className="shrink-0 text-xs text-neg hover:underline"
          >
            Clear
          </button>
        )}
      </div>
    </Field>
  );
}

export default function SetupPage() {
  const [view, setView] = useState<SettingsView | null>(null);
  const [form, setForm] = useState<Form | null>(null);
  const [cleared, setCleared] = useState<Set<string>>(new Set());
  const [msg, setMsg] = useState("");
  const [test, setTest] = useState<ConnTest | null>(null);
  const [alertTest, setAlertTest] = useState<{ ok: boolean; enabled: boolean } | null>(null);
  const [busy, setBusy] = useState(false);

  function hydrate(v: SettingsView) {
    setView(v);
    setForm({
      kalshi_env: v.kalshi_env ?? "demo",
      series: v.series ?? "KXBTC15M,KXBTCD",
      start_mode: v.start_mode ?? "paper",
      autostart: v.autostart ?? false,
      starting_balance: v.starting_balance?.toString() ?? "1000",
      llm_enabled: v.llm_enabled ?? false,
      min_edge: v.min_edge?.toString() ?? "0.04",
      fee_buffer: v.fee_buffer?.toString() ?? "0.02",
      vol_lookback_s: v.vol_lookback_s?.toString() ?? "900",
      alert_equity_drop_pct: v.alert_equity_drop_pct?.toString() ?? "5",
      kalshi_api_key_id: "",
      kalshi_private_key: "",
      anthropic_api_key: "",
      gemini_api_key: "",
      alert_webhook_url: "",
    });
    setCleared(new Set());
  }

  useEffect(() => {
    api.getSettings().then(hydrate).catch(() => setMsg("Engine offline."));
  }, []);

  function set<K extends keyof Form>(key: K, val: Form[K]) {
    setForm((f) => (f ? { ...f, [key]: val } : f));
  }

  function clearSecret(key: string) {
    setCleared((c) => new Set(c).add(key));
    set(key as keyof Form, "" as any);
    setMsg(`${key} will be cleared on save.`);
  }

  async function save() {
    if (!form) return;
    setBusy(true);
    setMsg("");
    const payload: Record<string, any> = {
      kalshi_env: form.kalshi_env,
      series: form.series,
      start_mode: form.start_mode,
      autostart: form.autostart,
      starting_balance: parseFloat(form.starting_balance),
      llm_enabled: form.llm_enabled,
      min_edge: parseFloat(form.min_edge),
      fee_buffer: parseFloat(form.fee_buffer),
      vol_lookback_s: parseInt(form.vol_lookback_s, 10),
      alert_equity_drop_pct: parseFloat(form.alert_equity_drop_pct),
    };
    for (const key of SECRET_KEYS) {
      if (cleared.has(key)) payload[key] = "__clear__";
      else if (form[key]) payload[key] = form[key];
    }
    try {
      const updated = await api.saveSettings(payload);
      hydrate(updated);
      setMsg("Saved & applied ✓ — engine reloaded with new settings.");
    } catch (e: any) {
      setMsg(`Save failed: ${e?.message}`);
    } finally {
      setBusy(false);
    }
  }

  async function runTest() {
    setTest(null);
    try {
      setTest(await api.testConnection());
    } catch (e: any) {
      setTest({ ok: false, detail: e?.message });
    }
  }

  async function runAlertTest() {
    setAlertTest(null);
    try {
      setAlertTest(await api.testAlert());
    } catch (e: any) {
      setAlertTest({ ok: false, enabled: false });
    }
  }

  if (!form) {
    return <Card>{msg || "Loading settings…"}</Card>;
  }

  return (
    <div className="max-w-3xl space-y-6">
      {msg && (
        <div className="rounded-lg border border-line bg-bg-card px-4 py-2 text-sm text-muted">
          {msg}
        </div>
      )}

      <Card
        title="Kalshi connection"
        actions={
          <Badge tone={form.kalshi_env === "prod" ? "live" : "paper"}>
            {form.kalshi_env.toUpperCase()}
          </Badge>
        }
      >
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <Field label="Environment" hint="Use demo to test safely.">
              <select
                value={form.kalshi_env}
                onChange={(e) => set("kalshi_env", e.target.value)}
                className={input}
              >
                <option value="demo">Demo (sandbox)</option>
                <option value="prod">Production (real money)</option>
              </select>
            </Field>
            <SecretInput
              label="API Key ID"
              meta={view?.kalshi_api_key_id}
              value={form.kalshi_api_key_id}
              onChange={(v) => set("kalshi_api_key_id", v)}
              onClear={() => clearSecret("kalshi_api_key_id")}
            />
          </div>
          <Field
            label="RSA private key (PEM)"
            hint="Paste the full -----BEGIN PRIVATE KEY----- block from Kalshi."
          >
            <textarea
              rows={5}
              value={form.kalshi_private_key}
              onChange={(e) => set("kalshi_private_key", e.target.value)}
              placeholder={
                view?.kalshi_private_key.set
                  ? `•••• keep current (${view.kalshi_private_key.hint})`
                  : "-----BEGIN PRIVATE KEY-----"
              }
              className={`${input} font-mono text-xs`}
            />
          </Field>
          {view?.kalshi_private_key.set && (
            <button
              type="button"
              onClick={() => clearSecret("kalshi_private_key")}
              className="text-xs text-neg hover:underline"
            >
              Clear stored private key
            </button>
          )}
          <div className="flex items-center gap-3">
            <Button onClick={runTest}>Test Kalshi connection</Button>
            {test && (
              <Badge tone={test.ok ? "pos" : "neg"}>
                {test.ok
                  ? `OK · ${test.env} · $${test.balance_usd?.toFixed(2)}`
                  : `Failed: ${test.detail}`}
              </Badge>
            )}
          </div>
        </div>
      </Card>

      <Card title="AI models (optional)">
        <div className="space-y-4">
          <p className="text-xs leading-relaxed text-muted">
            When enabled, Claude and Gemini review recent performance and advise
            how aggressively to bet. They never place trades on their own. Leave
            this off to run on the math model alone.
          </p>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={form.llm_enabled}
              onChange={(e) => set("llm_enabled", e.target.checked)}
            />
            Let AI advise how aggressively to bet
          </label>
          <div className="grid grid-cols-2 gap-4">
            <SecretInput
              label="Anthropic API key (Claude)"
              meta={view?.anthropic_api_key}
              value={form.anthropic_api_key}
              onChange={(v) => set("anthropic_api_key", v)}
              onClear={() => clearSecret("anthropic_api_key")}
            />
            <SecretInput
              label="Google API key (Gemini)"
              meta={view?.gemini_api_key}
              value={form.gemini_api_key}
              onChange={(v) => set("gemini_api_key", v)}
              onClear={() => clearSecret("gemini_api_key")}
            />
          </div>
        </div>
      </Card>

      <Card title="Alerts (optional)">
        <div className="space-y-4">
          <SecretInput
            label="Webhook URL (Discord / Slack)"
            meta={view?.alert_webhook_url}
            value={form.alert_webhook_url}
            onChange={(v) => set("alert_webhook_url", v)}
            onClear={() => clearSecret("alert_webhook_url")}
            placeholder="Paste a Discord/Slack incoming webhook URL to receive alerts."
          />
          <Field
            label="Alert me if my account drops by (%)"
            hint="Sends an alert when the account falls this far from its peak."
          >
            <input
              type="number"
              step="0.5"
              value={form.alert_equity_drop_pct}
              onChange={(e) => set("alert_equity_drop_pct", e.target.value)}
              className={`${input} num`}
            />
          </Field>
          <div className="flex items-center gap-3">
            <Button onClick={runAlertTest}>Test alert</Button>
            {alertTest && (
              <Badge tone={alertTest.ok ? "pos" : "neg"}>
                {alertTest.ok
                  ? alertTest.enabled
                    ? "Alert sent ✓"
                    : "No webhook set (logged only)"
                  : "Failed"}
              </Badge>
            )}
          </div>
        </div>
      </Card>

      <Card title="Trading parameters">
        <p className="mb-4 text-xs leading-relaxed text-muted">
          Defaults work well to start. These control which markets the bot
          watches and how picky it is. You can fine-tune risk limits later on
          the Controls page.
        </p>
        <div className="grid grid-cols-2 gap-4 md:grid-cols-3">
          <Field
            label="Markets to watch"
            hint="Kalshi series prefixes, comma-separated."
          >
            <input
              value={form.series}
              onChange={(e) => set("series", e.target.value)}
              className={`${input} num`}
            />
          </Field>
          <Field label="Start in" hint="Which mode the bot boots into.">
            <select
              value={form.start_mode}
              onChange={(e) => set("start_mode", e.target.value)}
              className={input}
            >
              <option value="paper">Paper (practice)</option>
              <option value="live">Live (real money)</option>
            </select>
          </Field>
          <Field
            label="Practice balance ($)"
            hint="Pretend bankroll for paper mode."
          >
            <input
              type="number"
              value={form.starting_balance}
              onChange={(e) => set("starting_balance", e.target.value)}
              className={`${input} num`}
            />
          </Field>
          <Field
            label="Minimum edge to bet"
            hint="How good a deal must be, e.g. 0.04 = 4%."
          >
            <input
              type="number"
              step="0.01"
              value={form.min_edge}
              onChange={(e) => set("min_edge", e.target.value)}
              className={`${input} num`}
            />
          </Field>
          <Field
            label="Fee cushion"
            hint="Extra margin to cover fees and spread."
          >
            <input
              type="number"
              step="0.01"
              value={form.fee_buffer}
              onChange={(e) => set("fee_buffer", e.target.value)}
              className={`${input} num`}
            />
          </Field>
          <Field
            label="Volatility window (s)"
            hint="How far back to measure price swings."
          >
            <input
              type="number"
              value={form.vol_lookback_s}
              onChange={(e) => set("vol_lookback_s", e.target.value)}
              className={`${input} num`}
            />
          </Field>
        </div>
        <label className="mt-4 flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={form.autostart}
            onChange={(e) => set("autostart", e.target.checked)}
          />
          Start the bot automatically when it boots up
        </label>
      </Card>

      <div className="flex items-center gap-3">
        <Button tone="primary" onClick={save} disabled={busy}>
          {busy ? "Saving…" : "Save & apply"}
        </Button>
        <span className="text-xs text-muted">
          Saving hot-reloads the engine; it restarts if it was running.
        </span>
      </div>
    </div>
  );
}
