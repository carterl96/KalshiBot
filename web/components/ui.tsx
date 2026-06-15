// Small shared UI primitives.

import { ReactNode } from "react";

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
  className = "",
}: {
  label: string;
  value: ReactNode;
  className?: string;
}) {
  return (
    <div className="rounded-xl border border-line bg-bg-card p-4">
      <div className="text-xs uppercase tracking-wide text-muted">{label}</div>
      <div className={`mt-1 font-mono text-2xl font-semibold ${className}`}>
        {value}
      </div>
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
