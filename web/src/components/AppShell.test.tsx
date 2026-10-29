import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { Role } from "../api/types";
import { makeMe, mockFetch, renderApp, seedSession } from "../test/utils";

async function navLabels(role: Role, path = "/") {
  seedSession();
  mockFetch({
    "GET /me": { body: makeMe(role) },
    "GET /orders": { body: [] },
    "GET /approvals": { body: [] },
    "GET /cases": { body: [] },
  });
  renderApp(path);
  const nav = await screen.findByTestId("side-nav");
  return within(nav)
    .getAllByRole("link")
    .map((a) => a.textContent);
}

describe("role-based navigation", () => {
  it("customers see their orders and cases", async () => {
    expect(await navLabels("customer")).toEqual(["My orders", "My cases", "Our policies", "Privacy & data", "Help"]);
    expect(await screen.findByRole("heading", { name: "My orders" })).toBeInTheDocument();
  });

  it("location managers see approvals and cases", async () => {
    expect(await navLabels("location_manager")).toEqual(["Approvals", "Cases to handle", "Cases", "Policies", "Help"]);
    expect(await screen.findByRole("heading", { name: "Approvals" })).toBeInTheDocument();
  });

  it.each<Role>(["franchisee_owner", "hq_owner"])("%s also sees insights", async (role) => {
    expect(await navLabels(role)).toEqual(["Approvals", "Cases to handle", "Cases", "Insights", "Policies", "Help"]);
    expect(await screen.findByRole("heading", { name: "Approvals" })).toBeInTheDocument();
  });

  it("does not show a staff screen to a customer who types its URL", async () => {
    await navLabels("customer", "/approvals");
    expect(await screen.findByText("Page not found")).toBeInTheDocument();
  });

  it("shows business, user and role in the top bar and signs out", async () => {
    await navLabels("hq_owner");
    expect(screen.getByTestId("business-name")).toHaveTextContent("Acme Foods");
    expect(screen.getAllByText("Asha Rao").length).toBeGreaterThan(0);
    expect(screen.getByText("HQ owner")).toBeInTheDocument();
    mockFetch({ "GET /auth/businesses": { body: [] } });
    await userEvent.setup().click(screen.getByRole("button", { name: "Sign out" }));
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(sessionStorage.getItem("resolvedesk.session")).toBeNull();
  });

  it("renders the role's manual on the Help page", async () => {
    await navLabels("location_manager", "/help");
    expect(await screen.findByRole("heading", { name: "Location manager guide" })).toBeInTheDocument();
  });
});

describe("privacy contact", () => {
  it("links the tenant's privacy contact in the footer and shows it on the Help page", async () => {
    seedSession();
    mockFetch({
      "GET /me": { body: makeMe("customer") },
      "GET /orders": { body: [] },
      "GET /cases": { body: [] },
      "GET /meta/privacy": { body: { name: "Privacy desk", email: "privacy@acme.test" } },
    });
    renderApp("/help");
    expect(await screen.findByRole("link", { name: "privacy@acme.test" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Privacy contact" })).toHaveAttribute(
      "href",
      "mailto:privacy@acme.test",
    );
  });
});
