import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { refreshAccessToken } from "./refreshAccessToken";
import { getStoredRefreshToken, getStoredToken, setStoredTokens } from "./tokenStorage";

function jsonResponse(body: unknown, init?: ResponseInit): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
    ...init,
  });
}

describe("refreshAccessToken", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("resolves null without calling fetch when no refresh token is stored", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const result = await refreshAccessToken();
    expect(result).toBeNull();
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("exchanges the stored refresh token and updates storage on success", async () => {
    setStoredTokens("old-access", "old-refresh");
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse({ access_token: "new-access", refresh_token: "new-refresh" }),
    );

    const result = await refreshAccessToken();

    expect(result).toBe("new-access");
    expect(getStoredToken()).toBe("new-access");
    expect(getStoredRefreshToken()).toBe("new-refresh");
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const [url, init] = fetchSpy.mock.calls[0];
    expect(String(url)).toContain("/auth/refresh");
    expect(JSON.parse(init?.body as string)).toEqual({ refresh_token: "old-refresh" });
  });

  it("clears stored tokens and returns null when the server rejects the refresh token", async () => {
    setStoredTokens("old-access", "already-rotated-refresh");
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "invalid refresh token" }), { status: 401 }),
    );

    const result = await refreshAccessToken();

    expect(result).toBeNull();
    expect(getStoredToken()).toBeNull();
    expect(getStoredRefreshToken()).toBeNull();
  });

  it("does not clear stored tokens on a network failure -- the refresh token may still be valid", async () => {
    setStoredTokens("old-access", "old-refresh");
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("network error"));

    const result = await refreshAccessToken();

    expect(result).toBeNull();
    expect(getStoredRefreshToken()).toBe("old-refresh");
  });

  it("shares a single in-flight refresh across concurrent callers", async () => {
    // The critical property: refresh tokens are single-use/rotating server-side, so
    // two concurrent refresh calls presenting the same (about-to-be-stale) token
    // would have the second one rejected as a reuse and revoke the whole chain. This
    // proves only one call actually reaches the network.
    setStoredTokens("old-access", "old-refresh");
    let resolveFetch!: (value: Response) => void;
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockReturnValue(
      new Promise<Response>((resolve) => {
        resolveFetch = resolve;
      }),
    );

    const first = refreshAccessToken();
    const second = refreshAccessToken();

    resolveFetch(jsonResponse({ access_token: "new-access", refresh_token: "new-refresh" }));

    const [firstResult, secondResult] = await Promise.all([first, second]);

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(firstResult).toBe("new-access");
    expect(secondResult).toBe("new-access");
  });

  it("allows a fresh refresh after a prior one has completed", async () => {
    setStoredTokens("old-access", "old-refresh");
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse({ access_token: "access-2", refresh_token: "refresh-2" }))
      .mockResolvedValueOnce(jsonResponse({ access_token: "access-3", refresh_token: "refresh-3" }));

    await refreshAccessToken();
    const second = await refreshAccessToken();

    expect(second).toBe("access-3");
    expect(fetchSpy).toHaveBeenCalledTimes(2);
  });
});
