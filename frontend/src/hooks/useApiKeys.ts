import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "../api/client";
import type { components } from "../api/generated/types";

export type UserSummary = components["schemas"]["UserRead"];
export type ApiKey = components["schemas"]["ApiKeyRead"];
export type ApiKeyCreated = components["schemas"]["ApiKeyCreated"];

export function useUsers() {
  return useQuery({
    queryKey: ["users"],
    queryFn: async () => {
      const { data, error } = await apiClient.GET("/api/v1/auth/users");
      if (error) throw error;
      return data;
    },
  });
}

export function useApiKeys(userId: string | undefined) {
  return useQuery({
    queryKey: ["api-keys", userId],
    queryFn: async () => {
      const { data, error } = await apiClient.GET("/api/v1/auth/users/{user_id}/api-keys", {
        params: { path: { user_id: userId! } },
      });
      if (error) throw error;
      return data;
    },
    enabled: Boolean(userId),
  });
}

export function useCreateApiKey() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (params: { userId: string; name: string; expiresAt?: string }) => {
      const { data, error } = await apiClient.POST("/api/v1/auth/users/{user_id}/api-keys", {
        params: { path: { user_id: params.userId } },
        body: { name: params.name, expires_at: params.expiresAt ?? null },
      });
      if (error) throw error;
      return data;
    },
    onSuccess: (_data, params) => {
      queryClient.invalidateQueries({ queryKey: ["api-keys", params.userId] });
    },
  });
}

export function useRevokeApiKey(userId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (apiKeyId: string) => {
      const { data, error } = await apiClient.POST("/api/v1/auth/api-keys/{api_key_id}/revoke", {
        params: { path: { api_key_id: apiKeyId } },
      });
      if (error) throw error;
      return data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["api-keys", userId] });
    },
  });
}
