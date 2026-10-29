import { useEffect, useState } from "react";
import { NavLink, Link, Outlet } from "react-router-dom";
import { useAuth } from "../auth/session";
import { homePath, isStaff, navFor, roleLabel } from "../lib/roles";
import type { NavItem } from "../lib/roles";
import { api } from "../api/endpoints";
import { useApi } from "../lib/useApi";
import { ThemeSwitcher } from "./theme";
import { Badge, Button, cx } from "./ui";

const ICON: Record<NavItem["icon"], string> = {
  orders: "M3 4h2l2.4 10.2a2 2 0 0 0 2 1.8h7.7a2 2 0 0 0 2-1.6L21 8H6.2M9 20a1 1 0 1 0 0-2 1 1 0 0 0 0 2Zm9 0a1 1 0 1 0 0-2 1 1 0 0 0 0 2Z",
  cases: "M4 5h16v11H8l-4 4V5Z",
  approvals: "M9 12l2 2 4-4M12 3l7 3v6c0 4.4-3 7.8-7 9-4-1.2-7-4.6-7-9V6l7-3Z",
  dev: "M8 9l-4 3 4 3m8-6l4 3-4 3M14 6l-4 12",
  insights: "M4 20V10m6 10V4m6 16v-7m4 7H2",
  growth: "M3 17l6-6 4 4 8-8m0 0h-5m5 0v5",
  privacy: "M12 3l7 3v6c0 4.4-3 7.8-7 9-4-1.2-7-4.6-7-9V6l7-3Zm-2 8.5h4v3h-4v-3Z",
  help: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Zm-2.5-11.5a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .9-1 1.5V14m0 3h.01",
};

function Icon({ name }: { name: NavItem["icon"] }) {
  return (
    <svg viewBox="0 0 24 24" className="h-4 w-4 shrink-0" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={ICON[name]} />
    </svg>
  );
}

export function Logo() {
  // Onest wordmark; the orange dot is the one place the brand colour appears.
  return (
    <span className="font-brand text-base font-semibold tracking-tight text-foreground">
      ResolveDesk<span className="text-brand">.</span>
    </span>
  );
}

/** True once the page has scrolled, so the header can blur only then. */
function useScrolled(): boolean {
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);
  return scrolled;
}

export function AppShell() {
  const { me, businessName, signOut } = useAuth();
  const scrolled = useScrolled();
  if (!me) return null;
  // The dev panel exists only where the API mounts /admin (dev/test): a 404 hides it.
  const { data: chaos } = useApi(() => (me.role === "hq_owner" ? api.chaos() : Promise.reject(new Error("n/a"))), [me.role]);
  const { data: privacy } = useApi(() => api.privacyContact(), [me.role]);
  // Count of cases waiting for a person, shown on the "Cases to handle" item (staff only).
  const { data: queue } = useApi(() => (isStaff(me.role) ? api.caseQueue() : Promise.reject(new Error("n/a"))), [me.role]);
  const waiting = queue?.length ?? 0;
  const base = navFor(me.role, me.growth_enabled === true);
  const nav = chaos ? [...base.slice(0, -1), { to: "/dev", label: "Dev panel", icon: "dev" as const }, base[base.length - 1]] : base;

  const linkClass = ({ isActive }: { isActive: boolean }) =>
    cx(
      "flex items-center gap-2.5 rounded-md border px-3 py-2 text-sm font-medium transition-colors duration-200",
      isActive ? "border-card-edge text-foreground" : "border-transparent text-muted-foreground hover:text-foreground",
    );

  return (
    <div className="min-h-screen bg-background text-foreground">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded focus:bg-background focus:px-3 focus:py-2 focus:text-foreground">
        Skip to content
      </a>
      <header
        className={cx(
          "sticky top-0 z-30 border-b transition-colors duration-200",
          scrolled ? "border-border bg-background/70 backdrop-blur-md" : "border-transparent bg-transparent",
        )}
      >
        <div className="mx-auto flex h-14 max-w-6xl items-center gap-3 px-6 sm:px-12">
          <Link to={homePath(me.role)} className="shrink-0" aria-label="ResolveDesk home">
            <Logo />
          </Link>
          <span className="hidden h-5 w-px bg-border sm:block" aria-hidden="true" />
          <span className="min-w-0 truncate text-sm text-muted-foreground" data-testid="business-name">
            {businessName}
          </span>
          <div className="ml-auto flex items-center gap-2 sm:gap-3">
            <div className="hidden min-w-0 text-right sm:block">
              <div className="truncate text-sm font-medium text-foreground">{me.name}</div>
            </div>
            <Badge tone="neutral" className="hidden sm:inline-flex">{roleLabel(me.role)}</Badge>
            <NavLink to="/help" className="hidden rounded-md px-2.5 py-1.5 text-sm text-muted-foreground transition-colors duration-200 hover:text-foreground sm:inline-flex">
              Help
            </NavLink>
            <ThemeSwitcher />
            <Button variant="outline" onClick={signOut} className="h-8 px-3">
              Sign out
            </Button>
          </div>
        </div>
        {/* Phone: nav as a scrollable tab row under the top bar. */}
        <nav aria-label="Main" className="border-t border-border md:hidden">
          <ul className="flex gap-1 overflow-x-auto px-3 py-2">
            {nav.map((item) => (
              <li key={item.to}>
                <NavLink to={item.to} className={linkClass}>
                  <Icon name={item.icon} />
                  {item.label}{item.to === "/queue" && waiting > 0 && <Badge tone="accent" className="ml-auto">{waiting}</Badge>}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
      </header>

      <div className="mx-auto flex max-w-6xl gap-8 px-6 sm:px-12">
        <aside className="hidden w-52 shrink-0 py-6 md:block">
          <nav aria-label="Main">
            <ul className="space-y-1" data-testid="side-nav">
              {nav.map((item) => (
                <li key={item.to}>
                  <NavLink to={item.to} className={linkClass}>
                    <Icon name={item.icon} />
                    {item.label}{item.to === "/queue" && waiting > 0 && <Badge tone="accent" className="ml-auto">{waiting}</Badge>}
                  </NavLink>
                </li>
              ))}
            </ul>
          </nav>
          <div className="card-chai mt-8 p-3 text-xs text-muted-foreground">
            <div className="font-medium text-foreground">{me.name}</div>
            <div className="truncate">{me.email}</div>
          </div>
        </aside>
        <main id="main" className="min-w-0 flex-1 py-6 sm:py-8">
          <Outlet />
        </main>
      </div>
      <footer className="mx-auto max-w-6xl border-t border-border px-6 py-4 text-xs text-muted-foreground sm:px-12">
        {privacy && privacy.email ? (
          <a href={`mailto:${privacy.email}`} title={privacy.name} className="underline underline-offset-2 transition-colors duration-200 hover:text-brand">
            Privacy contact
          </a>
        ) : (
          <NavLink to="/help" className="underline underline-offset-2 transition-colors duration-200 hover:text-brand">
            Privacy contact
          </NavLink>
        )}
      </footer>
    </div>
  );
}
