import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "../api/client";
import type { components } from "../api/generated/types";

export type Trade = components["schemas"]["TradeRead"];
export type TradeCreate = components["schemas"]["TradeCreate"];
export type TradeChangeRequest = components["schemas"]["TradeChangeRequestRead"];

export function useTrades(bookId?: string) {
  return useQuery({
    queryKey: ["trades", bookId],
    queryFn: async () => {
      const { data, error } = await apiClient.GET("/api/v1/trades", {
        params: { query: bookId ? { book_id: bookId } : {} },
      });
      if (error) throw error;
      return data;
    },
  });
}

export function useCreateTrade() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (payload: TradeCreate) => {
      const { data, error } = await apiClient.POST("/api/v1/trades", { body: payload });
      if (error) throw error;
      return data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["trades"] });
    },
  });
}

export function useConfirmTrade() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (tradeId: string) => {
      const { data, error } = await apiClient.POST("/api/v1/trades/{trade_id}/confirm", {
        params: { path: { trade_id: tradeId } },
      });
      if (error) throw error;
      return data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["trades"] });
    },
  });
}

export function useRequestCancellation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (params: { tradeId: string; reason: string }) => {
      const { data, error } = await apiClient.POST("/api/v1/trades/{trade_id}/cancellations", {
        params: { path: { trade_id: params.tradeId } },
        body: { reason: params.reason },
      });
      if (error) throw error;
      return data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["trades"] });
      queryClient.invalidateQueries({ queryKey: ["pending-change-requests"] });
    },
  });
}

export function useRequestAmendment() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (params: { tradeId: string; changes: Record<string, unknown>; reason: string }) => {
      const { data, error } = await apiClient.POST("/api/v1/trades/{trade_id}/amendments", {
        params: { path: { trade_id: params.tradeId } },
        body: { changes: params.changes, reason: params.reason },
      });
      if (error) throw error;
      return data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["trades"] });
      queryClient.invalidateQueries({ queryKey: ["pending-change-requests"] });
    },
  });
}
