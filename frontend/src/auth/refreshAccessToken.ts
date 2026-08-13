import { clearStoredToken, getStoredRefreshToken, setStoredTokens } from "./tokenStorage";

// Same base URL apiClient uses (see api/client.ts's comment) -- no `/api/v1`
// baked in here either, since this module builds the full path itself below.
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

let inFlightRefresh: Promise<string | null> | null = null;

/**
 * Exchanges the stored refresh token for a new access+refresh pair and updates
 * storage in place. Returns the new access token, or null (having cleared stored
 * tokens) if the refresh itself fails -- an invalid/expired/reused refresh token
 * means the session is genuinely over, not something a retry can fix.
 *
 * Concurrent callers share a single in-flight refresh rather than each firing their
 * own: refresh tokens are single-use/rotating on the backend (POST /auth/refresh),
 * so two concurrent refresh calls would race -- whichever lands second presents an
 * already-rotated token, which the backend treats as reuse/a possible compromise and
 * responds to by revoking the *entire* token chain, forcing a real re-login. This is
 * exactly the scenario several API calls 401ing at once (the access token just
 * expired mid-session) would otherwise trigger.
 */
export function refreshAccessToken(): Promise<string | null> {
  if (inFlightRefresh) return inFlightRefresh;

  const refreshToken = getStoredRefreshToken();
  if (!refreshToken) return Promise.resolve(null);

  inFlightRefresh = (async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
      if (!response.ok) {
        clearStoredToken();
        return null;
      }
      const data = (await response.json()) as { access_token: string; refresh_token: string };
      setStoredTokens(data.access_token, data.refresh_token);
      return data.access_token;
    } catch {
      // Network failure -- don't clear stored tokens (the refresh token itself may
      // still be perfectly valid, the request just never reached the server); the
      // caller falls back to surfacing the original 401 and can retry later.
      return null;
    } finally {
      inFlightRefresh = null;
    }
  })();

  return inFlightRefresh;
}
