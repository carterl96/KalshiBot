// Small shared UI primitives.

import { ReactNode, useState } from "react";

export function Card({
  title,
  children,
  actions,
  className = "",
}: {
  title?: string;
  children: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`rounded-xl border border-line bg-bg-card p-4 ${className}`}
    >
      {(title || actions) && (
        <div className="mb-3 flex items-center justify-between">
          {title && (
            <h3 className="text-sm font-medium text-muted">{title}</h3>
          )}
          {actions}
        </div>
      )}
      {children}
    </div>
  );
}

export function Stat({
  label,
  value,
  hint,
  className = "",
}: {
  label: string;
  value: ReactNode;
  hint?: string;
  className?: string;
}) {
  return (
    <div className="rounded-xl border border-line bg-bg-card p-4">
      <div className="text-xs uppercase tracking-wide text-muted">{label}</div>
      <div className={`mt-1 font-mono text-2xl font-semibold ${className}`}>
        {value}
      </div>
      {hint && <div className="mt-1 text-[10px] text-muted">{hint}</div>}
    </div>
  );
}

export function Badge({
  children,
  tone = "muted",
}: {
  children: ReactNode;
  tone?: "muted" | "pos" | "neg" | "paper" | "live" | "accent";
}) {
  const tones: Record<string, string> = {
    muted: "bg-bg-hover text-muted",
    pos: "bg-pos/15 text-pos",
    neg: "bg-neg/15 text-neg",
    paper: "bg-paper/15 text-paper",
    live: "bg-live/20 text-live",
    accent: "bg-accent/15 text-accent",
  };
  return (
    <span
      className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-semibold ${tones[tone]}`}
    >
      {children}
    </span>
  );
}

export function Button({
  children,
  onClick,
  tone = "default",
  disabled,
  type = "button",
}: {
  children: ReactNode;
  onClick?: () => void;
  tone?: "default" | "primary" | "danger" | "ghost";
  disabled?: boolean;
  type?: "button" | "submit";
}) {
  const tones: Record<string, string> = {
    default: "bg-bg-hover hover:bg-line text-text",
    primary: "bg-accent hover:bg-accent/80 text-white",
    danger: "bg-neg hover:bg-neg/80 text-white",
    ghost: "hover:bg-bg-hover text-muted",
  };
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`rounded-lg px-3 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${tones[tone]}`}
    >
      {children}
    </button>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return (
    <div className="py-10 text-center text-sm text-muted">{children}</div>
  );
}

// A titled section with an optional plain-language description and right-aligned
// actions. Use it to group related controls and reduce visual density.
export function Section({
  title,
  description,
  actions,
  children,
  className = "",
}: {
  title?: string;
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`rounded-xl border border-line bg-bg-card p-5 ${className}`}
    >
      {(title || actions || description) && (
        <div className="mb-4 flex items-start justify-between gap-3">
          <div>
            {title && (
              <h3 className="text-sm font-semibold text-text">{title}</h3>
            )}
            {description && (
              <p className="mt-1 text-xs leading-relaxed text-muted">
                {description}
              </p>
            )}
          </div>
          {actions && <div className="shrink-0">{actions}</div>}
        </div>
      )}
      {children}
    </div>
  );
}

// A collapsible "Advanced" disclosure. Collapsed by default so simple defaults
// stay up front and power-user knobs are tucked away.
export function Disclosure({
  label = "Advanced settings",
  hint,
  defaultOpen = false,
  children,
}: {
  label?: string;
  hint?: string;
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="rounded-xl border border-line bg-bg-card">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between p-4 text-left"
      >
        <span>
          <span className="text-sm font-medium text-text">{label}</span>
          {hint && (
            <span className="ml-2 text-xs text-muted">{hint}</span>
          )}
        </span>
        <span className="text-muted">{open ? "▲" : "▼"}</span>
      </button>
      {open && <div className="px-4 pb-4">{children}</div>}
    </div>
  );
}

// Friendly on/off switch.
export function Toggle({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label?: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className="inline-flex items-center gap-2"
    >
      <span
        className={`relative h-5 w-9 rounded-full transition-colors ${
          checked ? "bg-accent" : "bg-bg-hover"
        }`}
      >
        <span
          className={`absolute top-0.5 h-4 w-4 rounded-full bg-white transition-transform ${
            checked ? "translate-x-4" : "translate-x-0.5"
          }`}
        />
      </span>
      {label && <span className="text-sm text-text">{label}</span>}
    </button>
  );
}

// Styled select matching the form inputs across the app.
export function Select({
  value,
  onChange,
  children,
  className = "",
}: {
  value: string;
  onChange: (v: string) => void;
  children: ReactNode;
  className?: string;
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className={`rounded-lg border border-line bg-bg-soft px-3 py-2 text-sm outline-none focus:border-accent ${className}`}
    >
      {children}
    </select>
  );
}
