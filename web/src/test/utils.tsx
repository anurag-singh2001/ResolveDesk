import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import { App } from "../App";
import type { Me, Role } from "../api/types";
import { AuthProvider } from "../auth/session";

export interface Call {
  method: string;
  path: string;
  headers: Record<string, string>;
  body: unknown;
}

type Handler = (call: Call) => { status?: number; body?: unknown } | undefined;

/** Stub global fetch with a route table: "GET /me" → handler or static response. */
export function mockFetch(routes: Record<string, Handler | { status?: number; body?: unknown }>) {
  const calls: Call[] = [];
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input));
    const method = (init?.method ?? "GET").toUpperCase();
    const call: Call = {
      method,
      path: url.pathname,
      headers: (init?.headers ?? {}) as Record<string, string>,
      body: init?.body ? JSON.parse(String(init.body)) : undefined,
    };
    calls.push(call);
    const route = routes[`${method} ${url.pathname}`];
    const res = typeof route === "function" ? route(call) : route;
    const status = res?.status ?? (route ? 200 : 404);
    const body = res?.body ?? (route ? null : { detail: "not found" });
    return new Response(body === null ? "" : JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fn);
  return { fn, calls };
}

export function makeMe(role: Role, extra: Partial<Me> = {}): Me {
  return {
    user_id: "u-1",
    name: "Asha Rao",
    email: "asha@example.com",
    role,
    location_ids: [],
    brand_ids: [],
    tenant: { slug: "acme", name: "Acme Foods", vertical: "cloud_kitchen" },
    ...extra,
  };
}

export function seedSession(token = "tok-1") {
  sessionStorage.setItem(
    "resolvedesk.session",
    JSON.stringify({ token, expiresAt: null, tenant: "acme", businessName: "Acme Foods" }),
  );
}

export function renderApp(path = "/") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  );
}
