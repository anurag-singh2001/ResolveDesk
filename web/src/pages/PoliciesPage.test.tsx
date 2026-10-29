import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { PolicyDoc, Role } from "../api/types";
import { makeMe, mockFetch, renderApp, seedSession } from "../test/utils";

const HOSTILE = '<script>window.__pwned = 1</script><img src=x onerror="window.__pwned = 1"> **bold** [x](javascript:alert(1))';

const docs: PolicyDoc[] = [
  {
    id: "late_delivery_v3",
    title: "Late delivery policy",
    topic: "late_delivery",
    version: 3,
    in_force_from: "2026-09-01",
    in_force_to: null,
    scope: "org",
    sections: [
      { id: "2.1", anchor: "late_delivery_v3-2.1", title: "More than 45 minutes late", text: "We offer a voucher.\n\n- Up to Rs 150\n- Once per order" },
      { id: "2.2", anchor: "late_delivery_v3-2.2", title: HOSTILE, text: HOSTILE },
    ],
  },
];

function setup(role: Role) {
  seedSession();
  return mockFetch({
    "GET /me": { body: makeMe(role) },
    "GET /policies": { body: docs },
    "GET /orders": { body: [] },
    "GET /approvals": { body: [] },
    "GET /cases/queue": { body: [] },
    "GET /meta/privacy": { body: { name: "", email: "" } },
  });
}

describe("policies page", () => {
  it("shows documents and sections with an anchor per section, without the version, to a customer", async () => {
    setup("customer");
    renderApp("/policies");
    await screen.findByRole("heading", { name: "Our policies" });
    const section = document.getElementById("late_delivery_v3-2.1");
    expect(section).not.toBeNull();
    expect(within(section as HTMLElement).getByText("Up to Rs 150").tagName).toBe("LI");
    expect(screen.getByTestId("meta-late_delivery_v3")).toHaveTextContent("In force from 2026-09-01");
    expect(screen.getByTestId("meta-late_delivery_v3")).not.toHaveTextContent("Version");
    const link = screen.getAllByRole("link", { name: /2\.1 More than 45 minutes late/ })[0];
    expect(link).toHaveAttribute("href", "#late_delivery_v3-2.1");
  });

  it("shows the version and date in force to staff", async () => {
    setup("hq_owner");
    renderApp("/policies");
    await screen.findByRole("heading", { name: "Policies" });
    expect(screen.getByTestId("meta-late_delivery_v3")).toHaveTextContent("Version 3, in force from 2026-09-01");
  });

  it("renders markup in policy text as inert plain text", async () => {
    setup("customer");
    renderApp("/policies");
    await screen.findByRole("heading", { name: "Our policies" });
    const main = screen.getByRole("main");
    expect(main.querySelector("script")).toBeNull();
    expect(main.querySelector("img")).toBeNull();
    expect(main.querySelector("a[href^='javascript']")).toBeNull();
    expect((window as unknown as { __pwned?: number }).__pwned).toBeUndefined();
    // The literal characters are visible.
    expect(screen.getAllByText(/<script>window\.__pwned = 1<\/script>/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/\*\*bold\*\*/).length).toBeGreaterThan(0);
  });

  it("shows an empty state when nothing is published", async () => {
    seedSession();
    mockFetch({ "GET /me": { body: makeMe("customer") }, "GET /policies": { body: [] }, "GET /orders": { body: [] } });
    renderApp("/policies");
    expect(await screen.findByText("No policies are published yet")).toBeInTheDocument();
  });
});
