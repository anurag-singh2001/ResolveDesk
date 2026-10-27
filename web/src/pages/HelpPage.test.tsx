import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { makeMe, mockFetch, renderApp, seedSession } from "../test/utils";

function setup(role: "customer" | "hq_owner", putStatus = 200) {
  seedSession();
  return mockFetch({
    "GET /me": { body: makeMe(role) },
    "GET /meta/privacy": { body: { name: "", email: "" } },
    "GET /orders": { body: [] },
    "GET /me/preferences": { body: { language: "en" } },
    "PUT /me/preferences": (call) =>
      putStatus === 200
        ? { body: call.body }
        : { status: putStatus, body: { detail: "nope" } },
  });
}

describe("language selector", () => {
  it("lets a customer choose a language and sends it to the server", async () => {
    const { calls } = setup("customer");
    renderApp("/help");
    const select = await screen.findByLabelText("Language for our messages");
    await waitFor(() => expect(select).toBeEnabled());
    await userEvent.selectOptions(select, "hi");
    await waitFor(() => expect(select).toHaveValue("hi"));
    const put = calls.find((c) => c.method === "PUT" && c.path === "/me/preferences");
    expect(put?.body).toEqual({ language: "hi" });
  });

  it("shows an error and keeps the old choice when saving fails", async () => {
    setup("customer", 500);
    renderApp("/help");
    const select = await screen.findByLabelText("Language for our messages");
    await waitFor(() => expect(select).toBeEnabled());
    await userEvent.selectOptions(select, "hi-Latn");
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not save");
    expect(select).toHaveValue("en");
  });

  it("is not shown to staff", async () => {
    const { calls } = setup("hq_owner");
    renderApp("/help");
    await screen.findByRole("heading", { name: "Help" });
    expect(screen.queryByLabelText("Language for our messages")).not.toBeInTheDocument();
    expect(calls.some((c) => c.path === "/me/preferences")).toBe(false);
  });
});
