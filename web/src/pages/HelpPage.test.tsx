import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { makeMe, mockFetch, renderApp, seedSession } from "../test/utils";

type Role = "customer" | "location_manager" | "franchisee_owner" | "hq_owner";

function setup(role: Role) {
  seedSession();
  return mockFetch({
    "GET /me": { body: makeMe(role) },
    "GET /meta/privacy": { body: { name: "", email: "" } },
    "GET /orders": { body: [] },
  });
}

describe("language", () => {
  it("has no language picker: we reply in the language the customer writes in", async () => {
    const { calls } = setup("customer");
    renderApp("/help");
    await screen.findByRole("heading", { name: "Help" });
    expect(screen.queryByLabelText("Language for our messages")).not.toBeInTheDocument();
    expect(calls.some((c) => c.path === "/me/preferences")).toBe(false);
  });

  it("is quiet for staff", async () => {
    const { calls } = setup("hq_owner");
    renderApp("/help");
    await screen.findByRole("heading", { name: "Help" });
    expect(calls.some((c) => c.path === "/me/preferences")).toBe(false);
  });
});

const SECTIONS = ["Dashboard", "Segments", "Brand signals", "Campaign calendar", "Offer ROI and manual spend", "Scenario lab"];

describe("manual sections per role", () => {
  it.each(["location_manager", "franchisee_owner", "hq_owner"] as const)("%s manual covers all six newer screens", async (role) => {
    setup(role);
    renderApp("/help");
    await screen.findByRole("heading", { name: "Help" });
    for (const name of SECTIONS) {
      expect(await screen.findByRole("heading", { level: 2, name })).toBeInTheDocument();
    }
  });

  it("only the HQ manual describes Brand signals as a page the reader has", async () => {
    setup("hq_owner");
    renderApp("/help");
    expect(await screen.findByText(/compares each brand's repeat-customer rate/)).toBeInTheDocument();
  });

  it("a manager's manual says Brand signals and manual spend are not theirs", async () => {
    setup("location_manager");
    renderApp("/help");
    expect(await screen.findByText(/is an HQ owner page/)).toBeInTheDocument();
    expect(screen.getByText(/is for HQ owners only, so you will not see that form/)).toBeInTheDocument();
  });

  it("the customer manual lists none of the staff screens as sections", async () => {
    setup("customer");
    renderApp("/help");
    expect(await screen.findByRole("heading", { level: 2, name: "Screens for staff" })).toBeInTheDocument();
    for (const name of SECTIONS) {
      expect(screen.queryByRole("heading", { level: 2, name })).not.toBeInTheDocument();
    }
  });
});
