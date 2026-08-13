import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "../api/client";
import type { TradeChangeRequest } from "./useTrades";

export function usePendingChangeRequests() {
  return useQuery({
    queryKey: ["pending-change-requests"],
    queryFn: async () => {
      const { data, error } = await apiClient.GET("/api/v1/trade-change-requests");
      if (error) throw error;
      return data as TradeChangeRequest[];
    },
  });
}

export function useApproveChangeRequest() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (params: { id: string; note?: string }) => {
      const { data, error } = await apiClient.POST("/api/v1/trade-change-requests/{change_request_id}/approve", {
        params: { path: { change_request_id: params.id } },
        body: { note: params.note ?? null },
      });
      if (error) throw error;
      return data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["pending-change-requests"] });
      queryClient.invalidateQueries({ queryKey: ["trades"] });
    },
  });
}

export function useRejectChangeRequest() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (params: { id: string; note?: string }) => {
      const { data, error } = await apiClient.POST("/api/v1/trade-change-requests/{change_request_id}/reject", {
        params: { path: { change_request_id: params.id } },
        body: { note: params.note ?? null },
      });
      if (error) throw error;
      return data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["pending-change-requests"] });
      queryClient.invalidateQueries({ queryKey: ["trades"] });
    },
  });
}
