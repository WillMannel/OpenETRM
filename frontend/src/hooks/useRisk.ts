import { useMutation, useQuery } from "@tanstack/react-query";

import { apiClient } from "../api/client";
import type { components } from "../api/generated/types";

export type VarResult = components["schemas"]["VarResultRead"];
export type DeltaLadder = components["schemas"]["DeltaLadderRead"];

export function useRunVar() {
  return useMutation({
    mutationFn: async (params: { bookId: string; asOfDate: string; confidenceLevel: 95 | 99 }) => {
      const { data, error } = await apiClient.POST("/api/v1/risk/var/run", {
        body: {
          book_id: params.bookId,
          as_of_date: params.asOfDate,
          commodity: "HENRY_HUB",
          confidence_level: params.confidenceLevel,
          scenario_window_days: 250,
        },
      });
      if (error) throw error;
      return data;
    },
  });
}

export function useDeltaLadder(bookId: string | undefined, asOfDate: string | undefined) {
  return useQuery({
    queryKey: ["delta-ladder", bookId, asOfDate],
    queryFn: async () => {
      const { data, error } = await apiClient.GET("/api/v1/risk/delta-ladder", {
        params: { query: { book_id: bookId!, as_of_date: asOfDate! } },
      });
      if (error) throw error;
      return data;
    },
    enabled: Boolean(bookId && asOfDate),
  });
}
