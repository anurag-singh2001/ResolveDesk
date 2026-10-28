import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { makeMe, mockFetch, renderApp, seedSession } from "../test/utils";

function setup(role: "customer" | "hq_owner") {
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
