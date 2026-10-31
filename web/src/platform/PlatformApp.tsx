import { useState } from "react";
import type { FormEvent } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import { ApiError } from "../api/client";
import { Logo } from "../components/AppShell";
import { ThemeSwitcher } from "../components/theme";
import { Alert, Button, EmptyState, Field, PageHeader, cx, inputClass } from "../components/ui";
import { AiPage } from "./AiPage";
import { HealthPage } from "./HealthPage";
import { JobsPage } from "./JobsPage";
import { LogsPage } from "./LogsPage";
import { PlatformProvider, usePlatform } from "./session";

export const NOT_ENABLED = "The platform portal is not enabled";

const NAV = [
  { to: "/platform", label: "Health", end: true },
  { to: "/platform/jobs", label: "Scheduled jobs", end: false },
  { to: "/platform/logs", label: "Logs and alerts", end: false },
  { to: "/platform/ai", label: "AI performance", end: false },
  { to: "/platform/lab", label: "Scenario lab", end: false },
];

function ComingSoon({ title, what }: { title: string; what: string }) {
  return (
    <>
      <PageHeader title={title} />
      <EmptyState title="Coming soon">{what} There is nothing to show yet, and this page does not show sample numbers.</EmptyState>
    </>
  );
}

function NotEnabled() {
  return (
    <main className="mx-auto max-w-xl px-6 py-16">
      <EmptyState title={NOT_ENABLED}>This server has no platform admin set up. Nothing here is available until the owner turns it on.</EmptyState>
    </main>
  );
}

function PlatformLogin() {
  const { signIn, notice } = usePlatform();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await signIn(email.trim(), password);
    } catch (err) {
      if (err instanceof ApiError && err.status === 429) setError("Too many attempts, try again in a few minutes.");
      else if (err instanceof ApiError && err.status === 401) setError("Wrong email or password.");
      else if (!(err instanceof ApiError && err.status === 404)) setError("Could not sign in. Please try again.");
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto max-w-sm px-6 py-16">
      <div className="mb-6 text-center"><Logo /></div>
      <h1 className="mb-1 text-center text-2xl font-medium text-foreground">Platform sign in</h1>
      <p className="mb-6 text-center text-sm text-muted-foreground">For the platform owner. This is separate from the business sign in.</p>
      <form onSubmit={onSubmit} className="card-chai space-y-4 p-5">
        {(error || notice) && <Alert tone={error ? "danger" : "info"}>{error ?? notice}</Alert>}
        <Field label="Email" htmlFor="platform-email">
          <input id="platform-email" type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} className={inputClass} />
        </Field>
        <Field label="Password" htmlFor="platform-password">
          <input id="platform-password" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} className={inputClass} />
        </Field>
        <Button type="submit" loading={busy} className="w-full">Sign in</Button>
      </form>
    </main>
  );
}

function Shell() {
  const { signOut } = usePlatform();
  const link = ({ isActive }: { isActive: boolean }) =>
    cx(
      "block whitespace-nowrap rounded-md border px-3 py-2 text-sm font-medium transition-colors duration-200",
      isActive ? "border-card-edge text-foreground" : "border-transparent text-muted-foreground hover:text-foreground",
    );
  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="border-b border-border">
        <div className="mx-auto flex h-14 max-w-6xl items-center gap-3 px-6 sm:px-12">
          <Logo />
          <span className="text-sm text-muted-foreground">Platform</span>
          <div className="ml-auto flex items-center gap-2 sm:gap-3">
            <ThemeSwitcher />
            <Button variant="outline" onClick={signOut} className="h-8 shrink-0 whitespace-nowrap px-3">Sign out</Button>
          </div>
        </div>
        <nav aria-label="Platform" className="mx-auto max-w-6xl">
          <ul className="flex gap-1 overflow-x-auto px-3 py-2 sm:px-9 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
            {NAV.map((n) => (
              <li key={n.to} className="shrink-0"><NavLink to={n.to} end={n.end} className={link}>{n.label}</NavLink></li>
            ))}
          </ul>
        </nav>
      </header>
      <main id="main" className="mx-auto min-w-0 max-w-6xl px-6 py-6 sm:px-12 sm:py-8">
        <Routes>
          <Route path="/platform" element={<HealthPage />} />
          <Route path="/platform/jobs" element={<JobsPage />} />
          <Route path="/platform/logs" element={<LogsPage />} />
          <Route path="/platform/ai" element={<AiPage />} />
          <Route path="/platform/lab" element={<ComingSoon title="Scenario lab" what="Running scenarios from here is planned." />} />
          <Route path="*" element={<EmptyState title="Page not found">That portal page does not exist.</EmptyState>} />
        </Routes>
      </main>
    </div>
  );
}

function Gate() {
  const { signedIn, disabled } = usePlatform();
  if (disabled) return <NotEnabled />;
  return signedIn ? <Shell /> : <PlatformLogin />;
}

export function PlatformApp() {
  return (
    <PlatformProvider>
      <Gate />
    </PlatformProvider>
  );
}
