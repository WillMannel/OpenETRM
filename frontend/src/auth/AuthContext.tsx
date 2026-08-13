import { createContext, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";

import { apiClient } from "../api/client";
import type { components } from "../api/generated/types";
import { clearStoredToken, getStoredRefreshToken, getStoredToken, setStoredTokens } from "./tokenStorage";

export type CurrentUser = components["schemas"]["UserRead"];
export type UserRole = CurrentUser["role"];

export interface AuthState {
  user: CurrentUser | null;
  isLoading: boolean;
  login: (username: string, password: string) => Promise<void>;
  register: (username: string, email: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthState | undefined>(undefined);

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  async function loadCurrentUser() {
    const { data, error } = await apiClient.GET("/api/v1/auth/me");
    if (error) {
      clearStoredToken();
      setUser(null);
    } else {
      setUser(data);
    }
    setIsLoading(false);
  }

  useEffect(() => {
    if (getStoredToken()) {
      void loadCurrentUser();
    } else {
      setIsLoading(false);
    }
  }, []);

  async function login(username: string, password: string) {
    const { data, error } = await apiClient.POST("/api/v1/auth/login", {
      body: { username, password },
    });
    if (error) throw new Error("Invalid username or password");
    setStoredTokens(data.access_token, data.refresh_token);
    await loadCurrentUser();
  }

  async function register(username: string, email: string, password: string) {
    const { error } = await apiClient.POST("/api/v1/auth/register", {
      body: { username, email, password },
    });
    if (error) {
      const detail = (error as { detail?: string }).detail;
      throw new Error(detail ?? "Registration failed");
    }
    await login(username, password);
  }

  function logout() {
    // Best-effort, fire-and-forget: revoke the access token (added to the server's
    // JWT denylist) and refresh token server-side so neither can be replayed even
    // though they haven't expired yet -- see ARCHITECTURE.md's "Enterprise SSO,
    // token refresh & revocation". Local state clears immediately regardless of
    // whether this network call succeeds; a user clicking "log out" shouldn't wait
    // on it, and it's still safe to skip (the tokens are just gone from this
    // browser) if it fails.
    const refreshToken = getStoredRefreshToken();
    apiClient
      .POST("/api/v1/auth/logout", { body: refreshToken ? { refresh_token: refreshToken } : {} })
      .catch(() => {
        // Network failure -- nothing to do; local logout still proceeds below.
      });
    clearStoredToken();
    setUser(null);
  }

  return (
    <AuthContext.Provider value={{ user, isLoading, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  );
}
