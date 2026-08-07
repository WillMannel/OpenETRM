// A thin wrapper around localStorage -- kept as its own module so the storage key and
// mechanism are defined in exactly one place (AuthContext reads/writes it, the API
// client's request middleware reads it too, without importing React).
const STORAGE_KEY = "openetrm.access_token";

export function getStoredToken(): string | null {
  return localStorage.getItem(STORAGE_KEY);
}

export function setStoredToken(token: string): void {
  localStorage.setItem(STORAGE_KEY, token);
}

export function clearStoredToken(): void {
  localStorage.removeItem(STORAGE_KEY);
}
