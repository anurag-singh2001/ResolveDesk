import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Consents, ErasureRequest, Role } from "../api/types";
import { makeMe, mockFetch, renderApp, seedSession } from "../test/utils";

function consents(granted: boolean): Consents {
  return {
    notice_version: "v1",
    consents: [{ purpose: "marketing", channel: "whatsapp", granted, updated_at: null }],
    history: [],
  };
}

const deferred: ErasureRequest = {
  id: "r-1",
  kind: "erasure",
  status: "deferred",
  reason: "A refund or payment linked to your orders is still being processed.",
  deferred_until: null,
  requested_at: "2026-10-27T10:00:00Z",
  completed_at: null,
};

function setup(role: Role = "customer", erasure: ErasureRequest | null = null) {
  seedSession();
  return mockFetch({
    "GET /me": { body: makeMe(role) },
    "GET /orders": { body: [] },
    "GET /me/consents": { body: consents(false) },
    "POST /me/consents/marketing": (call) => ({ body: consents((call.body as { granted: boolean }).granted) }),
    "GET /me/data-export": { body: { profile: { name: "A" }, processors: [] } },
    "GET /me/erasure-request": { body: erasure },
    "POST /me/erasure-request": { status: 201, body: deferred },
  });
}

describe("privacy page", () => {
  it("lets a customer turn marketing on and off", async () => {
    const { calls } = setup();
    renderApp("/privacy");
    const toggle = await screen.findByRole("switch", { name: /Marketing messages on WhatsApp/ });
    expect(toggle).not.toBeChecked();
    fireEvent.click(toggle);
    await waitFor(() => expect(screen.getByRole("switch")).toBeChecked());
    fireEvent.click(screen.getByRole("switch"));
    await waitFor(() => expect(screen.getByRole("switch")).not.toBeChecked());
    const posts = calls.filter((c) => c.method === "POST").map((c) => c.body);
    expect(posts).toEqual([{ granted: true }, { granted: false }]);
  });

  it("downloads the data", async () => {
    const create = vi.fn(() => "blob:x");
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: create, revokeObjectURL: vi.fn() }));
    const { calls } = setup();
    renderApp("/privacy");
    fireEvent.click(await screen.findByRole("button", { name: "Download my data" }));
    await waitFor(() => expect(create).toHaveBeenCalled());
    expect(calls.some((c) => c.path === "/me/data-export")).toBe(true);
  });

  it("files an erasure request and shows the deferred status with its reason", async () => {
    const { calls } = setup();
    renderApp("/privacy");
    fireEvent.click(await screen.findByRole("button", { name: "Request erasure" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path === "/me/erasure-request")).toBe(true));
  });

  it("shows an existing deferred request with the reason and no second button", async () => {
    setup("customer", deferred);
    renderApp("/privacy");
    const status = await screen.findByTestId("erasure-status");
    expect(status).toHaveTextContent("Deferred");
    expect(status).toHaveTextContent("still being processed");
    expect(screen.queryByRole("button", { name: "Request erasure" })).not.toBeInTheDocument();
  });

  it("is not available to staff", async () => {
    const { calls } = setup("hq_owner");
    renderApp("/privacy");
    expect(await screen.findByText("Page not found")).toBeInTheDocument();
    expect(calls.some((c) => c.path.startsWith("/me/"))).toBe(false);
  });
});
