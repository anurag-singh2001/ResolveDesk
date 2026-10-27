import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { ApiError, errorMessage } from "../api/client";
import { api } from "../api/endpoints";
import type { Business, DemoAccount } from "../api/types";
import { useAuth } from "../auth/session";
import { Logo } from "../components/AppShell";
import { Alert, Badge, Button, Field, inputClass } from "../components/ui";
import { roleLabel } from "../lib/roles";

export const WRONG_CREDENTIALS = "Wrong email or password.";
export const TOO_MANY_ATTEMPTS = "Too many attempts, try again in a few minutes.";

export function LoginPage() {
  const { signIn, notice } = useAuth();
  const [businesses, setBusinesses] = useState<Business[] | null>(null);
  const [businessesFailed, setBusinessesFailed] = useState(false);
  const [demo, setDemo] = useState<DemoAccount[]>([]);
  const [tenant, setTenant] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .businesses()
      .then((list) => {
        setBusinesses(list);
        if (list.length === 1) setTenant(list[0].slug);
      })
      // Endpoint missing or down: fall back to typing the business ID.
      .catch(() => setBusinessesFailed(true));
    // Dev only: the API answers 404 in prod, and then no panel is shown.
    api
      .demoAccounts()
      .then((list) => setDemo(Array.isArray(list) ? list : []))
      .catch(() => setDemo([]));
  }, []);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!tenant || !email || !password) {
      setError("Choose your business and enter your email and password.");
      return;
    }
    setSubmitting(true);
    try {
      await signIn(tenant.trim(), email.trim(), password, businesses?.find((b) => b.slug === tenant));
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) setError(WRONG_CREDENTIALS);
      else if (err instanceof ApiError && err.status === 429) setError(TOO_MANY_ATTEMPTS);
      else setError(errorMessage(err));
      setSubmitting(false);
    }
  }

  function fillDemo(acc: DemoAccount) {
    setTenant(acc.tenant);
    setEmail(acc.email);
    setPassword(acc.password);
    setError(null);
  }

  const businessName = (slug: string) => businesses?.find((b) => b.slug === slug)?.name ?? slug;

  return (
    <div className="flex min-h-screen flex-col bg-background lg:flex-row">
      <div className="flex flex-1 items-center justify-center px-4 py-10 sm:px-6">
        <div className="w-full max-w-sm">
          <Logo />
          <h1 className="mt-8 text-2xl font-medium tracking-tight text-foreground sm:text-3xl">Sign in</h1>
          <p className="mt-1.5 text-sm text-muted-foreground">Track your orders, report a problem, or review cases.</p>

          <form onSubmit={onSubmit} className="mt-8 space-y-5" noValidate aria-label="Sign in">
            {notice && <Alert tone="warning">{notice}</Alert>}
            {error && <Alert>{error}</Alert>}

            <Field label="Business" htmlFor="tenant">
              {businessesFailed ? (
                <input id="tenant" className={inputClass} value={tenant} onChange={(e) => setTenant(e.target.value)} placeholder="Business ID" autoComplete="organization" />
              ) : (
                <select
                  id="tenant"
                  className={inputClass}
                  value={tenant}
                  onChange={(e) => setTenant(e.target.value)}
                  disabled={businesses === null}
                >
                  <option value="">{businesses === null ? "Loading…" : "Choose your business"}</option>
                  {businesses?.map((b) => (
                    <option key={b.slug} value={b.slug}>
                      {b.name}
                    </option>
                  ))}
                </select>
              )}
            </Field>
            <Field label="Email" htmlFor="email">
              <input id="email" type="email" className={inputClass} value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" />
            </Field>
            <Field label="Password" htmlFor="password">
              <input id="password" type="password" className={inputClass} value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
            </Field>
            <Button type="submit" className="w-full" loading={submitting}>
              Sign in
            </Button>
          </form>
        </div>
      </div>

      {demo.length > 0 && (
        <aside aria-labelledby="demo-heading" className="border-t border-border px-4 py-8 sm:px-6 lg:w-[28rem] lg:border-l lg:border-t-0 lg:py-10">
          <div className="mx-auto max-w-md">
            <div className="flex items-center gap-2">
              <h2 id="demo-heading" className="font-montserrat text-sm font-semibold text-foreground">
                Demo accounts
              </h2>
              <Badge tone="warning">Dev only</Badge>
            </div>
            <p className="mt-1 text-xs text-muted-foreground">Click an account to fill the form, then sign in.</p>
            <ul className="mt-4 max-h-[70vh] space-y-2 overflow-y-auto pr-1">
              {demo.map((acc) => (
                <li key={`${acc.tenant}:${acc.email}`}>
                  <button
                    type="button"
                    onClick={() => fillDemo(acc)}
                    className="card-chai w-full px-3 py-2.5 text-left"
                  >
                    <span className="flex items-center justify-between gap-2">
                      <span className="truncate text-sm font-medium text-foreground">{acc.name}</span>
                      <Badge tone="accent">{roleLabel(acc.role)}</Badge>
                    </span>
                    <span className="mt-0.5 block truncate text-xs text-muted-foreground">
                      {businessName(acc.tenant)} · {acc.email}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        </aside>
      )}
    </div>
  );
}
