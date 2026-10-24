import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { SESSION_ENDED } from "../auth/session";
import { makeMe, mockFetch, renderApp, seedSession } from "../test/utils";

const businesses = [
  { slug: "acme", name: "Acme Foods", vertical: "cloud_kitchen" },
  { slug: "beanco", name: "Bean Co", vertical: "coffee_chain" },
];

async function fill(tenant: string, email: string, password: string) {
  const user = userEvent.setup();
  await waitFor(() => expect(screen.getByLabelText("Business")).toBeEnabled());
  await user.selectOptions(screen.getByLabelText("Business"), tenant);
  await user.type(screen.getByLabelText("Email"), email);
  await user.type(screen.getByLabelText("Password"), password);
  await user.click(screen.getByRole("button", { name: "Sign in" }));
}

describe("login page", () => {
  it("signs in and lands on the role's home page", async () => {
    const { calls } = mockFetch({
      "GET /auth/businesses": { body: businesses },
      "POST /auth/login": { body: { access_token: "t1", token_type: "bearer", expires_at: "2999-01-01T00:00:00Z" } },
      "GET /me": { body: makeMe("customer") },
      "GET /orders": { body: [] },
    });
    renderApp("/");
    await fill("beanco", "a@b.co", "pw");
    expect(await screen.findByRole("heading", { name: "My orders" })).toBeInTheDocument();
    const login = calls.find((c) => c.path === "/auth/login")!;
    expect(login.body).toEqual({ tenant: "beanco", email: "a@b.co", password: "pw" });
    expect(calls.find((c) => c.path === "/me")!.headers.Authorization).toBe("Bearer t1");
    expect(sessionStorage.getItem("resolvedesk.session")).toContain("t1");
    expect(localStorage.length).toBe(0);
  });

  it("shows a uniform message for wrong credentials", async () => {
    mockFetch({
      "GET /auth/businesses": { body: businesses },
      "POST /auth/login": { status: 401, body: { detail: "invalid credentials" } },
    });
    renderApp("/login");
    await fill("acme", "a@b.co", "nope");
    expect(await screen.findByRole("alert")).toHaveTextContent("Wrong email or password");
  });

  it("shows the lockout message on 429", async () => {
    mockFetch({
      "GET /auth/businesses": { body: businesses },
      "POST /auth/login": { status: 429, body: { detail: "too many attempts" } },
    });
    renderApp("/login");
    await fill("acme", "a@b.co", "nope");
    expect(await screen.findByRole("alert")).toHaveTextContent("Too many attempts, try again in a few minutes");
  });

  it("fills the form from a demo account", async () => {
    mockFetch({
      "GET /auth/businesses": { body: businesses },
      "GET /auth/demo-accounts": {
        body: [{ tenant: "beanco", email: "mgr@bean.co", name: "Ravi", role: "location_manager", password: "demo-pass" }],
      },
    });
    renderApp("/login");
    const panel = await screen.findByRole("complementary", { name: "Demo accounts" });
    await waitFor(() => expect(screen.getByLabelText("Business")).toBeEnabled());
    await userEvent.setup().click(within(panel).getByRole("button", { name: /Ravi/ }));
    expect(screen.getByLabelText("Business")).toHaveValue("beanco");
    expect(screen.getByLabelText("Email")).toHaveValue("mgr@bean.co");
    expect(screen.getByLabelText("Password")).toHaveValue("demo-pass");
  });

  it("hides the demo panel when the endpoint is absent and falls back to a business ID field", async () => {
    mockFetch({}); // every route 404s
    renderApp("/login");
    const field = await screen.findByPlaceholderText("Business ID");
    expect(field.tagName).toBe("INPUT");
    expect(screen.queryByText("Demo accounts")).not.toBeInTheDocument();
  });

  it("sends the user back to login with a notice after a 401", async () => {
    seedSession();
    mockFetch({
      "GET /me": { body: makeMe("customer") },
      "GET /orders": { status: 401, body: { detail: "expired" } },
      "GET /auth/businesses": { body: businesses },
    });
    renderApp("/orders");
    expect(await screen.findByText(SESSION_ENDED)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign in" })).toBeInTheDocument();
    expect(sessionStorage.getItem("resolvedesk.session")).toBeNull();
  });
});
