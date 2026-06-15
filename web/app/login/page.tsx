"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/store";
import { Button } from "@/components/ui";

export default function LoginPage() {
  const { login } = useAuth();
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await login(password);
      router.push("/");
    } catch (err: any) {
      setError(err?.message || "login failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center">
      <form
        onSubmit={submit}
        className="w-80 rounded-2xl border border-line bg-bg-card p-6"
      >
        <div className="mb-6 flex items-center gap-2">
          <span className="text-xl font-bold text-accent">◆</span>
          <span className="text-lg font-semibold">KalshiBot</span>
        </div>
        <label className="mb-1 block text-xs uppercase tracking-wide text-muted">
          Admin password
        </label>
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoFocus
          className="mb-4 w-full rounded-lg border border-line bg-bg-soft px-3 py-2 text-sm outline-none focus:border-accent"
        />
        {error && <div className="mb-3 text-sm text-neg">{error}</div>}
        <Button type="submit" tone="primary" disabled={busy}>
          {busy ? "Signing in…" : "Sign in"}
        </Button>
      </form>
    </div>
  );
}
