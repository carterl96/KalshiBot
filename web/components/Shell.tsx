"use client";

// App shell: left sidebar nav + top bar with engine status and mode badge.

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { useAuth, useEngine } from "@/lib/store";
import { Badge } from "./ui";

const NAV = [
  { href: "/", label: "Dashboard", icon: "▣" },
  { href: "/markets", label: "Markets", icon: "≋" },
  { href: "/controls", label: "Controls", icon: "⚙" },
  { href: "/ai", label: "AI Log", icon: "✦" },
  { href: "/history", label: "History", icon: "≡" },
  { href: "/backtest", label: "Backtest", icon: "◎" },
  { href: "/setup", label: "Setup", icon: "⚿" },
];

export function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { token, ready, logout } = useAuth();
  const { connected, health, state } = useEngine();

  // Gate: require auth for everything except /login.
  useEffect(() => {
    if (ready && !token && pathname !== "/login") router.replace("/login");
  }, [ready, token, pathname, router]);

  if (pathname === "/login") return <>{children}</>;
  if (!ready || !token) return null;

  const mode = state?.mode ?? health?.mode ?? "paper";
  const running = state?.running ?? health?.engine_running ?? false;

  return (
    <div className="flex min-h-screen">
      <aside className="flex w-56 flex-col border-r border-line bg-bg-soft">
        <div className="flex items-center gap-2 px-5 py-5">
          <span className="text-lg font-bold text-accent">◆</span>
          <span className="font-semibold tracking-tight">KalshiBot</span>
        </div>
        <nav className="flex-1 px-3">
          {NAV.map((item) => {
            const active = pathname === item.href;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`mb-1 flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors ${
                  active
                    ? "bg-bg-hover font-medium text-text"
                    : "text-muted hover:bg-bg-hover hover:text-text"
                }`}
              >
                <span className="w-4 text-center">{item.icon}</span>
                {item.label}
              </Link>
            );
          })}
        </nav>
        <button
          onClick={logout}
          className="m-3 rounded-lg px-3 py-2 text-left text-sm text-muted hover:bg-bg-hover hover:text-text"
        >
          Sign out
        </button>
      </aside>

      <div className="flex flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-line px-6 py-3">
          <div className="flex items-center gap-3">
            <span
              className={`h-2 w-2 rounded-full ${
                connected ? "bg-pos" : "bg-neg"
              }`}
              title={connected ? "stream connected" : "stream offline"}
            />
            <span className="text-sm text-muted">
              {connected ? "Live" : "Engine offline"}
              {health ? ` · ${health.latency_ms.toFixed(1)}ms` : ""}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <Badge tone={running ? "pos" : "muted"}>
              {running ? "RUNNING" : "STOPPED"}
            </Badge>
            <Badge tone={mode === "live" ? "live" : "paper"}>
              {mode.toUpperCase()}
            </Badge>
          </div>
        </header>
        <main className="flex-1 overflow-auto p-6">{children}</main>
      </div>
    </div>
  );
}
