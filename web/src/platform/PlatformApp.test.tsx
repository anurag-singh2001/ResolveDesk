import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { makeMe, mockFetch, renderApp, seedSession } from "../test/utils";
import { PLATFORM_KEY } from "./session";

const tenants = [
  { tenant_slug: "alpha", vertical_pack: "cloud_kitchen" },
  { tenant_slug: "beta", vertical_pack: "coffee_franchise" },
];
const cases = [
  { tenant_slug: "alpha", day: "2026-10-30", status: "open", case_count: 3 },
  { tenant_slug: "alpha", day: "2026-10-30", status: "closed", case_count: 4 },
  { tenant_slug: "beta", day: "2026-10-30", status: "open", case_count: 5 },
];
const approvals = [{ tenant_slug: "alpha", day: "2026-10-30", decision: "approved", mode: "human", approval_count: 2 }];
const activity = [
  { tenant_slug: "alpha", last_system_event_at: "2026-10-30T10:00:00Z" },
  { tenant_slug: "beta", last_system_event_at: null },
];
const usage = [
  { tenant_slug: "alpha", day: "2026-10-30", provider: "gemini", model: "flash", purpose: "main", outcome: "ok", run_count: 4, call_count: 10, failure_count: 1, tokens_in: 1000, tokens_out: 500, cost_micro_paise: 25_000_000, latency_ms_total: 5000 },
  { tenant_slug: "beta", day: "2026-10-29", provider: "groq", model: "m", purpose: "main", outcome: "fallback_used", run_count: 2, call_count: 2, failure_count: 0, tokens_in: 10, tokens_out: 10, cost_micro_paise: 0, latency_ms_total: 200 },
];
const jobs = [
  { tenant_slug: "alpha", day: "2026-10-30", job: "sweep", status: "ok", run_count: 6, finished_count: 6, duration_ms_total: 600, last_started_at: "2026-10-30T09:00:00Z" },
  { tenant_slug: "alpha", day: "2026-10-30", job: "sweep", status: "failed", run_count: 1, finished_count: 1, duration_ms_total: 50, last_started_at: "2026-10-30T09:30:00Z" },
];
const alerts = [
  { rule: "job_failed", scope: "sweep", status: "open", value: 3, threshold: 1, opened_at: "2026-10-30T09:00:00Z", last_seen_at: "2026-10-30T09:30:00Z", resolved_at: null },
  { rule: "escalation_spike", scope: "alpha", status: "resolved", value: 9, threshold: 5, opened_at: "2026-10-29T09:00:00Z", last_seen_at: "2026-10-29T10:00:00Z", resolved_at: "2026-10-29T11:00:00Z" },
];
const logs = [{ service: "api", level: "error", event_code: "request.failed", error_class: "ValueError", day: "2026-10-30", occurrences: 4, last_at: "2026-10-30T09:30:00Z" }];

const login = { "POST /platform/auth/login": { body: { access_token: "plat-tok", token_type: "bearer", expires_at: null } } };
const data = {
  "GET /platform/tenants": { body: tenants },
  "GET /platform/cases": { body: cases },
  "GET /platform/approvals": { body: approvals },
  "GET /platform/activity": { body: activity },
  "GET /platform/ai-usage": { body: usage },
  "GET /platform/jobs": { body: jobs },
  "GET /platform/alerts": { body: alerts },
  "GET /platform/logs": { body: logs },
};

async function signIn() {
  await userEvent.type(await screen.findByLabelText("Email"), "ops@example.test");
  await userEvent.type(screen.getByLabelText("Password"), "pw");
  await userEvent.click(screen.getByRole("button", { name: /Sign in/ }));
}

beforeEach(() => {
  sessionStorage.clear();
});

describe("platform portal", () => {
  it("shows its own login, not the business one, and keeps the token under its own key", async () => {
    const { calls } = mockFetch({ ...login, ...data });
    renderApp("/platform");
    expect(await screen.findByRole("heading", { name: "Platform sign in" })).toBeInTheDocument();
    expect(screen.queryByLabelText(/business/i)).not.toBeInTheDocument();
    await signIn();
    expect(await screen.findByRole("heading", { name: "Health" })).toBeInTheDocument();
    expect(JSON.parse(sessionStorage.getItem(PLATFORM_KEY)!).token).toBe("plat-tok");
    expect(sessionStorage.getItem("resolvedesk.session")).toBeNull();
    expect(calls.some((c) => c.path === "/me")).toBe(false);
  });

  it("never sends a business token to the portal or the portal token anywhere else", async () => {
    seedSession("tenant-tok");
    const { calls } = mockFetch({ ...login, ...data, "GET /me": { body: makeMe("hq_owner") } });
    renderApp("/platform");
    await signIn();
    await screen.findByRole("heading", { name: "Health" });
    const platformCalls = calls.filter((c) => c.path.startsWith("/platform/") && c.path !== "/platform/auth/login");
    expect(platformCalls.length).toBeGreaterThan(0);
    for (const c of platformCalls) expect(c.headers.Authorization).toBe("Bearer plat-tok");
    for (const c of calls.filter((c) => !c.path.startsWith("/platform/"))) {
      expect(c.headers.Authorization).not.toBe("Bearer plat-tok");
    }
    expect(JSON.parse(sessionStorage.getItem("resolvedesk.session")!).token).toBe("tenant-tok");
  });

  it("shows per-business counts on Health", async () => {
    sessionStorage.setItem(PLATFORM_KEY, JSON.stringify({ token: "plat-tok", expiresAt: null }));
    mockFetch(data);
    renderApp("/platform");
    const row = (await screen.findByText("alpha", { selector: "td" })).closest("tr")!;
    expect(within(row).getByText("7")).toBeInTheDocument();
    expect(within(row).getByText("2")).toBeInTheDocument();
    expect(screen.getByText("No activity yet")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Logs and alerts" }).length).toBe(2);
  });

  it.each([401, 403])("clears the token and returns to sign in on %s", async (status) => {
    sessionStorage.setItem(PLATFORM_KEY, JSON.stringify({ token: "stale", expiresAt: null }));
    mockFetch({ ...data, "GET /platform/tenants": { status, body: { detail: "no" } } });
    renderApp("/platform");
    expect(await screen.findByRole("heading", { name: "Platform sign in" })).toBeInTheDocument();
    expect(sessionStorage.getItem(PLATFORM_KEY)).toBeNull();
    expect(screen.getByText(/session has ended/)).toBeInTheDocument();
  });

  it("shows a plain not-enabled page when the server answers 404", async () => {
    mockFetch({ "POST /platform/auth/login": { status: 404, body: { detail: "platform admin not enabled" } } });
    renderApp("/platform");
    await signIn();
    expect(await screen.findByRole("heading", { name: "The platform portal is not enabled" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Email")).not.toBeInTheDocument();
  });

  it("treats a 404 from a data route as an error, not as not enabled", async () => {
    sessionStorage.setItem(PLATFORM_KEY, JSON.stringify({ token: "plat-tok", expiresAt: null }));
    mockFetch({ ...data, "GET /platform/tenants": { status: 404, body: { detail: "not found" } } });
    renderApp("/platform");
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "The platform portal is not enabled" })).not.toBeInTheDocument();
    expect(sessionStorage.getItem(PLATFORM_KEY)).not.toBeNull();
  });

  it("drops the token when it expires while the page is open", async () => {
    const soon = new Date(Date.now() + 300).toISOString();
    sessionStorage.setItem(PLATFORM_KEY, JSON.stringify({ token: "plat-tok", expiresAt: soon }));
    mockFetch(data);
    renderApp("/platform/logs");
    expect(await screen.findByRole("heading", { name: "Platform sign in" }, { timeout: 2000 })).toBeInTheDocument();
    expect(sessionStorage.getItem(PLATFORM_KEY)).toBeNull();
  });

  it("shows a wrong-password message on 401 from login", async () => {
    mockFetch({ "POST /platform/auth/login": { status: 401, body: { detail: "invalid credentials" } } });
    renderApp("/platform");
    await signIn();
    expect(await screen.findByText("Wrong email or password.")).toBeInTheDocument();
    expect(sessionStorage.getItem(PLATFORM_KEY)).toBeNull();
  });

  it("lists alerts and error counts on Logs and alerts", async () => {
    sessionStorage.setItem(PLATFORM_KEY, JSON.stringify({ token: "plat-tok", expiresAt: null }));
    mockFetch(data);
    renderApp("/platform/logs");
    expect(await screen.findByRole("heading", { name: "Logs and alerts" })).toBeInTheDocument();
    const alert = (await screen.findByText("Job failed", { selector: "td" })).closest("tr")!;
    expect(within(alert).getByText("Open")).toBeInTheDocument();
    const log = screen.getByText("ValueError").closest("tr")!;
    expect(within(log).getByText("4")).toBeInTheDocument();
  });

  it("lists job run totals", async () => {
    sessionStorage.setItem(PLATFORM_KEY, JSON.stringify({ token: "plat-tok", expiresAt: null }));
    mockFetch(data);
    renderApp("/platform/jobs");
    expect(await screen.findByRole("heading", { name: "Scheduled jobs" })).toBeInTheDocument();
    const row = (await screen.findByText("Sweep", { selector: "td" })).closest("tr")!;
    expect(within(row).getByText("6")).toBeInTheDocument();
    expect(within(row).getByText("92 ms")).toBeInTheDocument();
  });

  it("shows AI performance with money in mono and rates from the counts", async () => {
    sessionStorage.setItem(PLATFORM_KEY, JSON.stringify({ token: "plat-tok", expiresAt: null }));
    mockFetch(data);
    renderApp("/platform/ai");
    expect(await screen.findByRole("heading", { name: "AI performance" })).toBeInTheDocument();
    const cost = (await screen.findAllByText("₹0.25"))[0];
    expect(cost.className).toContain("font-mono");
    expect(screen.getAllByText("10.0%").length).toBeGreaterThan(0);
    expect(screen.getAllByText("100.0%").length).toBeGreaterThan(0);
  });

  it("shows a plain coming-soon state on the scenario lab", async () => {
    sessionStorage.setItem(PLATFORM_KEY, JSON.stringify({ token: "plat-tok", expiresAt: null }));
    const { calls } = mockFetch(data);
    renderApp("/platform/lab");
    expect(await screen.findByRole("heading", { name: "Scenario lab" })).toBeInTheDocument();
    expect(screen.getByText("Coming soon")).toBeInTheDocument();
    expect(calls.length).toBe(0);
  });

  it("has no business navigation and a nav of the five portal pages", async () => {
    sessionStorage.setItem(PLATFORM_KEY, JSON.stringify({ token: "plat-tok", expiresAt: null }));
    mockFetch(data);
    renderApp("/platform");
    const nav = await screen.findByRole("navigation", { name: "Platform" });
    expect(within(nav).getAllByRole("link").map((a) => a.textContent)).toEqual([
      "Health", "Scheduled jobs", "Logs and alerts", "AI performance", "Scenario lab",
    ]);
    expect(screen.queryByRole("link", { name: "Cases" })).not.toBeInTheDocument();
  });

  it("leaves a signed-out business visitor on the business login", async () => {
    mockFetch({});
    renderApp("/cases");
    expect(await screen.findByRole("button", { name: /Sign in/ })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Platform sign in" })).not.toBeInTheDocument();
  });
});
