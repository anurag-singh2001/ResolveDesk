import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { Role } from "../api/types";
import { makeMe, mockFetch, renderApp, seedSession } from "../test/utils";

const zero = {
  timeout_rate: 0,
  transient_error_rate: 0,
  accept_then_timeout_rate: 0,
  error_rate: 0,
  processing_rate: 0,
  settle_after_polls: 2,
  delay_ms: 0,
  seed: 0,
};
const chaos = { payment: zero, vouchers: zero };
const report = { executed: ["a"], reconciled: ["b", "c"], escalated_cases: [], verified: [], pruned_threads: 0, events_published: 3 };

function setup(role: Role, extra: Parameters<typeof mockFetch>[0] = {}) {
  seedSession();
  return mockFetch({
    "GET /me": { body: makeMe(role) },
    "GET /approvals": { body: [] },
    ...extra,
  });
}

describe("dev panel", () => {
  it("is hidden from the nav when the API has no admin routes (404)", async () => {
    setup("hq_owner");
    renderApp("/approvals");
    await screen.findByTestId("side-nav");
    expect(within(screen.getByTestId("side-nav")).queryByText("Dev panel")).not.toBeInTheDocument();
  });

  it("is hidden from other roles and never asks the API", async () => {
    const { calls } = setup("location_manager", { "GET /admin/chaos": { body: chaos } });
    renderApp("/dev");
    expect(await screen.findByText("Page not found")).toBeInTheDocument();
    expect(calls.some((c) => c.path === "/admin/chaos")).toBe(false);
  });

  it("shows in the nav for hq_owner when the API exposes it", async () => {
    setup("hq_owner", { "GET /admin/chaos": { body: chaos } });
    renderApp("/approvals");
    expect(await within(await screen.findByTestId("side-nav")).findByText("Dev panel")).toBeInTheDocument();
  });

  it("posts chaos settings for one service", async () => {
    const { calls } = setup("hq_owner", { "GET /admin/chaos": { body: chaos }, "POST /admin/chaos": { body: chaos } });
    renderApp("/dev");
    const form = await screen.findByRole("form", { name: "Chaos settings for payment" });
    const input = within(form).getByLabelText("Timeout rate");
    await userEvent.clear(input);
    await userEvent.type(input, "0.5");
    await userEvent.click(screen.getByRole("button", { name: "Apply payment" }));
    const post = calls.find((c) => c.method === "POST" && c.path === "/admin/chaos");
    expect(post?.body).toMatchObject({ service: "payment", timeout_rate: 0.5, delay_ms: 0 });
  });

  it("applies a preset and resets a service", async () => {
    const { calls } = setup("hq_owner", { "GET /admin/chaos": { body: chaos }, "POST /admin/chaos": { body: chaos } });
    renderApp("/dev");
    await userEvent.click(await screen.findByRole("button", { name: "Payment times out after accepting" }));
    await userEvent.click(screen.getByRole("button", { name: "Reset vouchers" }));
    const posts = calls.filter((c) => c.method === "POST").map((c) => c.body);
    expect(posts).toEqual([{ service: "payment", accept_then_timeout_rate: 1 }, { service: "vouchers" }]);
  });

  it("runs the sweeper and shows the result", async () => {
    const { calls } = setup("hq_owner", { "GET /admin/chaos": { body: chaos }, "POST /admin/sweep": { body: report } });
    renderApp("/dev");
    await userEvent.click(await screen.findByRole("button", { name: "Run sweeper" }));
    expect(await screen.findByTestId("sweep-result")).toHaveTextContent("Executed 1, reconciled 2, verified 0, escalated 0 case(s).");
    expect(calls.some((c) => c.method === "POST" && c.path === "/admin/sweep")).toBe(true);
  });

  it("shows the simulated clock and moves or resets it", async () => {
    const at = (offset: number) => ({ now: "2026-10-27T10:00:00Z", offset_seconds: offset });
    let offset = 0;
    const { calls } = setup("hq_owner", {
      "GET /admin/chaos": { body: chaos },
      "GET /admin/clock": () => ({ body: at(offset) }),
      "POST /admin/clock": (c) => {
        const b = c.body as { advance_seconds?: number; reset?: boolean };
        offset = b.reset ? 0 : offset + (b.advance_seconds ?? 0);
        return { body: at(offset) };
      },
    });
    renderApp("/dev");
    expect(await screen.findByTestId("clock-offset")).toHaveTextContent("offset 0s");
    await userEvent.click(screen.getByRole("button", { name: "+1h" }));
    await userEvent.click(screen.getByRole("button", { name: "+4h" }));
    await userEvent.click(screen.getByRole("button", { name: "+1 day" }));
    await userEvent.click(screen.getByRole("button", { name: "+15 days" }));
    expect(await screen.findByText(`(offset ${3600 + 4 * 3600 + 86400 + 15 * 86400}s)`)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Reset clock" }));
    expect(await screen.findByText("(offset 0s)")).toBeInTheDocument();
    const posts = calls.filter((c) => c.method === "POST" && c.path === "/admin/clock").map((c) => c.body);
    expect(posts).toEqual([
      { advance_seconds: 3600 },
      { advance_seconds: 14400 },
      { advance_seconds: 86400 },
      { advance_seconds: 1296000 },
      { reset: true },
    ]);
  });
});
