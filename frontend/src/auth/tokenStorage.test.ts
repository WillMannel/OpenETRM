import { beforeEach, describe, expect, it } from "vitest";

import { clearStoredToken, getStoredRefreshToken, getStoredToken, setStoredTokens } from "./tokenStorage";

describe("tokenStorage", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("returns null for both tokens when nothing has been stored", () => {
    expect(getStoredToken()).toBeNull();
    expect(getStoredRefreshToken()).toBeNull();
  });

  it("stores and retrieves the access and refresh tokens together", () => {
    setStoredTokens("access-123", "refresh-456");
    expect(getStoredToken()).toBe("access-123");
    expect(getStoredRefreshToken()).toBe("refresh-456");
  });

  it("overwrites both tokens on a second call, e.g. after a refresh rotation", () => {
    setStoredTokens("access-1", "refresh-1");
    setStoredTokens("access-2", "refresh-2");
    expect(getStoredToken()).toBe("access-2");
    expect(getStoredRefreshToken()).toBe("refresh-2");
  });

  it("clears both tokens together", () => {
    setStoredTokens("access-123", "refresh-456");
    clearStoredToken();
    expect(getStoredToken()).toBeNull();
    expect(getStoredRefreshToken()).toBeNull();
  });
});
