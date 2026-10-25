import { describe, expect, it, vi } from "vitest";
import { mockFetch } from "../test/utils";
import { ApiError, configureClient, errorMessage, request } from "./client";

describe("api client", () => {
  it("sends the bearer token on authenticated calls", async () => {
    const { calls } = mockFetch({ "GET /me": { body: { ok: 1 } } });
    configureClient({ getToken: () => "abc", onUnauthorized: () => {} });
    await request("/me");
    expect(calls[0].headers.Authorization).toBe("Bearer abc");
  });

  it("sends no token on anonymous calls", async () => {
    const { calls } = mockFetch({ "POST /auth/login": { body: { access_token: "x" } } });
    configureClient({ getToken: () => "abc", onUnauthorized: () => {} });
    await request("/auth/login", { method: "POST", body: { a: 1 }, anonymous: true });
    expect(calls[0].headers.Authorization).toBeUndefined();
    expect(calls[0].headers["Content-Type"]).toBe("application/json");
    expect(calls[0].body).toEqual({ a: 1 });
  });

  it("reports a 401 on an authenticated call and throws ApiError", async () => {
    mockFetch({ "GET /cases": { status: 401, body: { detail: "not authenticated" } } });
    const onUnauthorized = vi.fn();
    configureClient({ getToken: () => "abc", onUnauthorized });
    await expect(request("/cases")).rejects.toMatchObject({ status: 401 });
    expect(onUnauthorized).toHaveBeenCalledOnce();
  });

  it("does not end the session on a 401 from login", async () => {
    mockFetch({ "POST /auth/login": { status: 401, body: { detail: "invalid credentials" } } });
    const onUnauthorized = vi.fn();
    configureClient({ getToken: () => null, onUnauthorized });
    await expect(request("/auth/login", { method: "POST", body: {}, anonymous: true })).rejects.toBeInstanceOf(ApiError);
    expect(onUnauthorized).not.toHaveBeenCalled();
  });

  it("exposes the API detail and turns 422 lists into a sentence", async () => {
    mockFetch({ "POST /approvals/p/decision": { status: 422, body: { detail: ["amount over cap", "order not yours"] } } });
    configureClient({ getToken: () => "abc", onUnauthorized: () => {} });
    const err = await request("/approvals/p/decision", { method: "POST", body: {} }).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(errorMessage(err)).toBe("amount over cap order not yours");
  });

  it("maps a network failure to status 0 with a readable message", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("Failed to fetch"))));
    const err = (await request("/me").catch((e: unknown) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(0);
    expect(errorMessage(err)).toMatch(/can't reach the server/i);
  });
});
