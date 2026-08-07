import { createContext, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";

import { apiClient } from "../api/client";
import type { components } from "../api/generated/types";
import { clearStoredToken, getStoredToken, setStoredToken } from "./tokenStorage";

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
    setStoredToken(data.access_token);
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
    clearStoredToken();
    setUser(null);
  }

  return (
    <AuthContext.Provider value={{ user, isLoading, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  );
}
