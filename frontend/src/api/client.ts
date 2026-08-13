import createClient from "openapi-fetch";

import { refreshAccessToken } from "../auth/refreshAccessToken";
import { getStoredRefreshToken, getStoredToken } from "../auth/tokenStorage";
import type { paths } from "./generated/types";

// Deliberately *without* the `/api/v1` prefix -- every call site already passes a
// full "/api/v1/..." schema path (e.g. `apiClient.GET("/api/v1/trades")`), matching
// the literal keys FastAPI's generated OpenAPI schema uses. Putting the prefix in
// both places would double it up in the final request URL.
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export const apiClient = createClient<paths>({ baseUrl: API_BASE_URL });

// Endpoints that must never trigger an auth-refresh retry on a 401: /login and
// /register 401 because of bad credentials, which refreshing can't fix, and /refresh
// itself 401ing means the refresh token is already invalid -- retrying it would just
// recurse into another failed refresh.
const REFRESH_EXEMPT_PATHS = new Set<string>([
  "/api/v1/auth/login",
  "/api/v1/auth/register",
  "/api/v1/auth/refresh",
]);

// Keyed by openapi-fetch's per-request id: a clone of each request, taken in
// onRequest before it's sent (so its body stream hasn't been consumed yet) -- the
// retry-after-refresh path in onResponse below needs an unconsumed copy to resend,
// since the original `request` object it receives has already had its body read by
// the fetch that produced the 401 response.
const pendingRequestClones = new Map<string, Request>();

apiClient.use({
  onRequest({ request, id }) {
    const token = getStoredToken();
    if (token) {
      request.headers.set("Authorization", `Bearer ${token}`);
    }
    pendingRequestClones.set(id, request.clone());
  },

  // A 401 on an authenticated request usually just means the (deliberately
  // short-lived) access token expired mid-session -- see ARCHITECTURE.md's
  // "Enterprise SSO, token refresh & revocation". Rather than bouncing the user to
  // the login page immediately, exchange the refresh token for a new access token
  // and retry the request exactly once, transparently.
  async onResponse({ id, response, schemaPath }) {
    const clone = pendingRequestClones.get(id);
    pendingRequestClones.delete(id);

    if (
      response.status !== 401 ||
      !clone ||
      REFRESH_EXEMPT_PATHS.has(schemaPath) ||
      !getStoredRefreshToken()
    ) {
      return response;
    }

    const newAccessToken = await refreshAccessToken();
    if (!newAccessToken) {
      return response; // refresh itself failed -- surface the original 401
    }

    clone.headers.set("Authorization", `Bearer ${newAccessToken}`);
    return fetch(clone);
  },

  onError({ id }) {
    pendingRequestClones.delete(id);
  },
});
