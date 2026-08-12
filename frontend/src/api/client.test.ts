import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setStoredTokens } from "../auth/tokenStorage";

function jsonResponse(body: unknown, init?: ResponseInit): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
    ...init,
  });
}

/**
 * openapi-fetch's createClient() captures `globalThis.fetch` into a closure *once*,
 * at the moment the client is constructed -- our `apiClient` singleton is
 * constructed at module-import time, before any per-test `vi.spyOn(globalThis,
 * "fetch")` in this file could possibly run. Stubbing fetch and then dynamically
 * re-importing (with a fresh module registry) is what actually gets the stub to
 * take effect, rather than silently hitting the real network with the original
 * fetch reference.
 */
async function freshApiClientWithMockedFetch(
  impl: (request: Request) => Response | Promise<Response>,
) {
  const fetchSpy = vi.fn(async (input: Request | string, init?: RequestInit) => {
    const request = input instanceof Request ? input : new Request(input, init);
    return impl(request);
  });
  vi.stubGlobal("fetch", fetchSpy);
  vi.resetModules();
  const { apiClient } = await import("./client");
  return { apiClient, fetchSpy };
}

describe("apiClient request URLs", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("does not double up the /api/v1 prefix -- baseUrl has none, call sites supply it", async () => {
    // Regression test: baseUrl used to default to ".../api/v1" *and* every call site
    // already passes a path starting with "/api/v1/...", so every real request this
    // app ever made was sent to ".../api/v1/api/v1/...", 404ing against the real
    // FastAPI backend (which only serves under a single "/api/v1" prefix). Nothing
    // caught this before because no test ever asserted on the actual request URL.
    const { apiClient, fetchSpy } = await freshApiClientWithMockedFetch(() => jsonResponse([]));

    await apiClient.GET("/api/v1/books");

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const requestArg = fetchSpy.mock.calls[0][0] as Request;
    expect(requestArg.url).toBe("http://localhost:8000/api/v1/books");
  });
});

describe("apiClient auth-refresh-on-401 retry", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("transparently refreshes and retries once when a request 401s", async () => {
    setStoredTokens("expired-access", "valid-refresh");

    const { apiClient, fetchSpy } = await freshApiClientWithMockedFetch((request) => {
      if (request.url.includes("/auth/refresh")) {
        return jsonResponse({ access_token: "fresh-access", refresh_token: "fresh-refresh" });
      }
      if (request.headers.get("Authorization") === "Bearer expired-access") {
        return new Response(JSON.stringify({ detail: "token expired" }), { status: 401 });
      }
      if (request.headers.get("Authorization") === "Bearer fresh-access") {
        return jsonResponse([{ id: "book-1", name: "Book One" }]);
      }
      throw new Error(`unexpected request: ${request.url}`);
    });

    const { data, error } = await apiClient.GET("/api/v1/books");

    expect(error).toBeUndefined();
    expect(data).toEqual([{ id: "book-1", name: "Book One" }]);
    // Original (401) + refresh + retry.
    expect(fetchSpy).toHaveBeenCalledTimes(3);
  });

  it("surfaces the original 401 when there is no refresh token to fall back to", async () => {
    // No setStoredTokens call -- nothing in storage.
    const { apiClient, fetchSpy } = await freshApiClientWithMockedFetch(
      () => new Response(JSON.stringify({ detail: "not authenticated" }), { status: 401 }),
    );

    const { error } = await apiClient.GET("/api/v1/books");

    expect(error).toEqual({ detail: "not authenticated" });
    expect(fetchSpy).toHaveBeenCalledTimes(1); // no refresh attempted
  });

  it("surfaces the original 401 when the refresh call itself fails", async () => {
    setStoredTokens("expired-access", "already-invalid-refresh");

    const { apiClient, fetchSpy } = await freshApiClientWithMockedFetch((request) => {
      if (request.url.includes("/auth/refresh")) {
        return new Response(JSON.stringify({ detail: "invalid refresh token" }), { status: 401 });
      }
      return new Response(JSON.stringify({ detail: "token expired" }), { status: 401 });
    });

    const { error } = await apiClient.GET("/api/v1/books");

    expect(error).toEqual({ detail: "token expired" });
    // Original request + the failed refresh attempt -- no third (retry) call.
    expect(fetchSpy).toHaveBeenCalledTimes(2);
  });

  it("does not attempt a refresh-retry for /auth/login itself", async () => {
    setStoredTokens("some-access", "some-refresh");
    const { apiClient, fetchSpy } = await freshApiClientWithMockedFetch(
      () => new Response(JSON.stringify({ detail: "invalid credentials" }), { status: 401 }),
    );

    const { error } = await apiClient.POST("/api/v1/auth/login", {
      body: { username: "someone", password: "wrong" },
    });

    expect(error).toEqual({ detail: "invalid credentials" });
    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });
});
