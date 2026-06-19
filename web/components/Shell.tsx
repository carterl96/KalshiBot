"use client";

// App shell: responsive nav (desktop sidebar / mobile top bar + slide-in
// drawer) with engine status and mode badge. Built mobile-first so the panel
// is usable on a phone.

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useAuth, useEngine } from "@/lib/store";
import { Badge } from "./ui";

const NAV = [
  { href: "/", label: "Dashboard", icon: "▣" },
  { href: "/markets", label: "Markets", icon: "≋" },
  { href: "/controls", label: "Controls", icon: "⚙" },
  { href: "/ai", label: "AI", icon: "✦" },
  { href: "/history", label: "History", icon: "≡" },
  { href: "/backtest", label: "Backtest", icon: "◎" },
  { href: "/setup", label: "Setup", icon: "⚿" },
];

function NavLinks({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  return (
    <>
      {NAV.map((item) => {
        const active = pathname === item.href;
        return (
          <Link
            key={item.href}
            href={item.href}
            onClick={onNavigate}
            className={`mb-1 flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition-colors ${
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
    </>
  );
}

function StatusPills() {
  const { connected, health, state } = useEngine();
  const mode = state?.mode ?? health?.mode ?? "paper";
  const running = state?.running ?? health?.engine_running ?? false;
  return (
    <div className="flex items-center gap-2">
      <span
        className={`h-2 w-2 rounded-full ${connected ? "bg-pos" : "bg-neg"}`}
        title={connected ? "stream connected" : "stream offline"}
      />
      <Badge tone={running ? "pos" : "muted"}>
        {running ? "RUNNING" : "STOPPED"}
      </Badge>
      <Badge tone={mode === "live" ? "live" : "paper"}>
        {mode.toUpperCase()}
      </Badge>
    </div>
  );
}

export function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { token, ready, logout } = useAuth();
  const [drawer, setDrawer] = useState(false);

  // Gate: require auth for everything except /login.
  useEffect(() => {
    if (ready && !token && pathname !== "/login") router.replace("/login");
  }, [ready, token, pathname, router]);

  // Close the mobile drawer whenever the route changes.
  useEffect(() => setDrawer(false), [pathname]);

  if (pathname === "/login") return <>{children}</>;
  if (!ready || !token) return null;

  return (
    <div className="flex min-h-screen">
      {/* Desktop sidebar */}
      <aside className="hidden w-56 flex-col border-r border-line bg-bg-soft md:flex">
        <div className="flex items-center gap-2 px-5 py-5">
          <span className="text-lg font-bold text-accent">◆</span>
          <span className="font-semibold tracking-tight">KalshiBot</span>
        </div>
        <nav className="flex-1 px-3">
          <NavLinks />
        </nav>
        <button
          onClick={logout}
          className="m-3 rounded-lg px-3 py-2 text-left text-sm text-muted hover:bg-bg-hover hover:text-text"
        >
          Sign out
        </button>
      </aside>

      {/* Mobile slide-in drawer */}
      {drawer && (
        <div className="fixed inset-0 z-40 md:hidden">
          <div
            className="absolute inset-0 bg-black/60"
            onClick={() => setDrawer(false)}
          />
          <aside className="absolute left-0 top-0 flex h-full w-64 flex-col border-r border-line bg-bg-soft">
            <div className="flex items-center justify-between px-5 py-5">
              <div className="flex items-center gap-2">
                <span className="text-lg font-bold text-accent">◆</span>
                <span className="font-semibold tracking-tight">KalshiBot</span>
              </div>
              <button
                onClick={() => setDrawer(false)}
                className="px-2 text-xl text-muted"
                aria-label="Close menu"
              >
                ✕
              </button>
            </div>
            <nav className="flex-1 px-3">
              <NavLinks onNavigate={() => setDrawer(false)} />
            </nav>
            <button
              onClick={logout}
              className="m-3 rounded-lg px-3 py-2 text-left text-sm text-muted hover:bg-bg-hover hover:text-text"
            >
              Sign out
            </button>
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex items-center justify-between gap-3 border-b border-line bg-bg/80 px-4 py-3 backdrop-blur md:px-6">
          <div className="flex items-center gap-3">
            <button
              onClick={() => setDrawer(true)}
              className="-ml-1 rounded-lg px-2 py-1 text-xl text-muted hover:bg-bg-hover md:hidden"
              aria-label="Open menu"
            >
              ☰
            </button>
            <span className="font-semibold tracking-tight md:hidden">
              KalshiBot
            </span>
          </div>
          <StatusPills />
        </header>
        <main className="flex-1 overflow-auto p-4 md:p-6">{children}</main>
      </div>
    </div>
  );
}
