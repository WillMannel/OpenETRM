// A thin wrapper around localStorage -- kept as its own module so the storage keys
// and mechanism are defined in exactly one place (AuthContext reads/writes them, the
// API client's request/refresh middleware read them too, without importing React).
const ACCESS_TOKEN_KEY = "openetrm.access_token";
const REFRESH_TOKEN_KEY = "openetrm.refresh_token";

export function getStoredToken(): string | null {
  return localStorage.getItem(ACCESS_TOKEN_KEY);
}

export function getStoredRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_TOKEN_KEY);
}

// Login and refresh both hand back an access+refresh pair together (POST
// /auth/refresh rotates the refresh token too -- see ARCHITECTURE.md's "Enterprise
// SSO, token refresh & revocation") -- there's no legitimate case for storing one
// without the other, so this is the only way either is written.
export function setStoredTokens(accessToken: string, refreshToken: string): void {
  localStorage.setItem(ACCESS_TOKEN_KEY, accessToken);
  localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken);
}

export function clearStoredToken(): void {
  localStorage.removeItem(ACCESS_TOKEN_KEY);
  localStorage.removeItem(REFRESH_TOKEN_KEY);
}
