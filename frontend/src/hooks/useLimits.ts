import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "../api/client";
import type { components } from "../api/generated/types";

export type BookLimit = components["schemas"]["BookLimitRead"];
export type BookLimitCreate = components["schemas"]["BookLimitCreate"];
export type LimitBreach = components["schemas"]["LimitBreachRead"];

export function useLimits(bookId?: string) {
  return useQuery({
    queryKey: ["limits", bookId],
    queryFn: async () => {
      const { data, error } = await apiClient.GET("/api/v1/limits", {
        params: { query: bookId ? { book_id: bookId } : {} },
      });
      if (error) throw error;
      return data;
    },
  });
}

export function useCreateOrUpdateLimit() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (payload: BookLimitCreate) => {
      const { data, error } = await apiClient.POST("/api/v1/limits", { body: payload });
      if (error) throw error;
      return data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["limits"] });
    },
  });
}

export function useOpenBreaches(bookId?: string) {
  return useQuery({
    queryKey: ["limit-breaches", bookId],
    queryFn: async () => {
      const { data, error } = await apiClient.GET("/api/v1/limits/breaches", {
        params: { query: bookId ? { book_id: bookId } : {} },
      });
      if (error) throw error;
      return data;
    },
  });
}

export function useAcknowledgeBreach() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (params: { breachId: string; note?: string }) => {
      const { data, error } = await apiClient.POST("/api/v1/limits/breaches/{breach_id}/acknowledge", {
        params: { path: { breach_id: params.breachId } },
        body: { note: params.note ?? null },
      });
      if (error) throw error;
      return data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["limit-breaches"] });
    },
  });
}
