import { NavLink, Link, Outlet } from "react-router-dom";
import { useAuth } from "../auth/session";
import { homePath, navFor, roleLabel } from "../lib/roles";
import type { NavItem } from "../lib/roles";
import { Badge, Button, cx } from "./ui";

const ICON: Record<NavItem["icon"], string> = {
  orders: "M3 4h2l2.4 10.2a2 2 0 0 0 2 1.8h7.7a2 2 0 0 0 2-1.6L21 8H6.2M9 20a1 1 0 1 0 0-2 1 1 0 0 0 0 2Zm9 0a1 1 0 1 0 0-2 1 1 0 0 0 0 2Z",
  cases: "M4 5h16v11H8l-4 4V5Z",
  approvals: "M9 12l2 2 4-4M12 3l7 3v6c0 4.4-3 7.8-7 9-4-1.2-7-4.6-7-9V6l7-3Z",
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
  return (
    <span className="flex items-center gap-2">
      <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-accent-600 text-white" aria-hidden="true">
        <svg viewBox="0 0 20 20" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
          <path d="M5 10.5l3 3 7-7" />
        </svg>
      </span>
      <span className="text-sm font-semibold tracking-tight text-slate-900">ResolveDesk</span>
    </span>
  );
}

export function AppShell() {
  const { me, businessName, signOut } = useAuth();
  if (!me) return null;
  const nav = navFor(me.role);

  const linkClass = ({ isActive }: { isActive: boolean }) =>
    cx(
      "flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition",
      isActive ? "bg-accent-50 text-accent-700" : "text-slate-600 hover:bg-slate-100 hover:text-slate-900",
    );

  return (
    <div className="min-h-screen">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded focus:bg-white focus:px-3 focus:py-2">
        Skip to content
      </a>
      <header className="sticky top-0 z-30 border-b border-slate-200 bg-white/90 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-7xl items-center gap-3 px-4 sm:px-6">
          <Link to={homePath(me.role)} className="shrink-0" aria-label="ResolveDesk home">
            <Logo />
          </Link>
          <span className="hidden h-5 w-px bg-slate-200 sm:block" aria-hidden="true" />
          <span className="min-w-0 truncate text-sm font-medium text-slate-700" data-testid="business-name">
            {businessName}
          </span>
          <div className="ml-auto flex items-center gap-2 sm:gap-3">
            <div className="hidden min-w-0 text-right sm:block">
              <div className="truncate text-sm font-medium text-slate-900">{me.name}</div>
            </div>
            <Badge tone="accent">{roleLabel(me.role)}</Badge>
            <NavLink to="/help" className="hidden rounded-lg px-2.5 py-1.5 text-sm text-slate-600 hover:bg-slate-100 sm:inline-flex">
              Help
            </NavLink>
            <Button variant="secondary" onClick={signOut} className="px-2.5 py-1.5">
              Sign out
            </Button>
          </div>
        </div>
        {/* Phone: nav as a scrollable tab row under the top bar. */}
        <nav aria-label="Main" className="border-t border-slate-100 md:hidden">
          <ul className="flex gap-1 overflow-x-auto px-3 py-2">
            {nav.map((item) => (
              <li key={item.to}>
                <NavLink to={item.to} className={linkClass}>
                  <Icon name={item.icon} />
                  {item.label}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
      </header>

      <div className="mx-auto flex max-w-7xl gap-8 px-4 sm:px-6">
        <aside className="hidden w-52 shrink-0 py-6 md:block">
          <nav aria-label="Main">
            <ul className="space-y-1" data-testid="side-nav">
              {nav.map((item) => (
                <li key={item.to}>
                  <NavLink to={item.to} className={linkClass}>
                    <Icon name={item.icon} />
                    {item.label}
                  </NavLink>
                </li>
              ))}
            </ul>
          </nav>
          <div className="mt-8 rounded-lg border border-slate-200 bg-white p-3 text-xs text-slate-500">
            <div className="font-medium text-slate-700">{me.name}</div>
            <div className="truncate">{me.email}</div>
          </div>
        </aside>
        <main id="main" className="min-w-0 flex-1 py-6 sm:py-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
