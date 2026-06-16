export const usd = (n: number | null | undefined) =>
  n == null ? "—" : `$${n.toFixed(2)}`;

export const pct = (n: number | null | undefined, digits = 1) =>
  n == null ? "—" : `${(n * 100).toFixed(digits)}%`;

export const cents = (n: number | null | undefined) =>
  n == null ? "—" : `${n}¢`;

export const signed = (n: number | null | undefined, digits = 2) =>
  n == null ? "—" : `${n >= 0 ? "+" : ""}${n.toFixed(digits)}`;

export const pnlClass = (n: number | null | undefined) =>
  n == null ? "" : n > 0 ? "text-pos" : n < 0 ? "text-neg" : "text-muted";

export function ago(tsSeconds: number): string {
  const d = Date.now() / 1000 - tsSeconds;
  if (d < 60) return `${Math.floor(d)}s ago`;
  if (d < 3600) return `${Math.floor(d / 60)}m ago`;
  if (d < 86400) return `${Math.floor(d / 3600)}h ago`;
  return `${Math.floor(d / 86400)}d ago`;
}

export function countdown(seconds: number): string {
  if (seconds <= 0) return "closed";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export function ts(tsSeconds: number): string {
  return new Date(tsSeconds * 1000).toLocaleTimeString();
}
