import { useMutation, useQuery } from "@tanstack/react-query";

import { apiClient } from "../api/client";
import type { components } from "../api/generated/types";
import type { Commodity } from "./useSelection";

export type VarResult = components["schemas"]["VarResultRead"];
export type VarMethod = components["schemas"]["VarMethod"];
export type DeltaLadder = components["schemas"]["DeltaLadderRead"];
export type StressResult = components["schemas"]["StressResultRead"];
export type PnlAttribution = components["schemas"]["PnlAttributionResponse"];
export type OptionGreeks = components["schemas"]["OptionGreeksRead"];

export function useRunVar() {
  return useMutation({
    mutationFn: async (params: {
      bookId: string;
      asOfDate: string;
      commodity: Commodity;
      confidenceLevel: 95 | 99;
      method: VarMethod;
    }) => {
      const { data, error } = await apiClient.POST("/api/v1/risk/var/run", {
        body: {
          book_id: params.bookId,
          as_of_date: params.asOfDate,
          commodity: params.commodity,
          confidence_level: params.confidenceLevel,
          scenario_window_days: 250,
          method: params.method,
        },
      });
      if (error) throw error;
      return data;
    },
  });
}

export function useDeltaLadder(bookId: string | undefined, asOfDate: string | undefined, commodity: Commodity) {
  return useQuery({
    queryKey: ["delta-ladder", bookId, asOfDate, commodity],
    queryFn: async () => {
      const { data, error } = await apiClient.GET("/api/v1/risk/delta-ladder", {
        params: { query: { book_id: bookId!, as_of_date: asOfDate!, commodity } },
      });
      if (error) throw error;
      return data;
    },
    enabled: Boolean(bookId && asOfDate),
  });
}

export function useRunStressTest() {
  return useMutation({
    mutationFn: async (params: { bookId: string; asOfDate: string; commodity: Commodity }) => {
      const { data, error } = await apiClient.POST("/api/v1/risk/stress-test", {
        body: { book_id: params.bookId, as_of_date: params.asOfDate, commodity: params.commodity },
      });
      if (error) throw error;
      return data;
    },
  });
}

export function useOptionGreeks() {
  return useMutation({
    mutationFn: async (params: { bookId: string; asOfDate: string; commodity: Commodity }) => {
      const { data, error } = await apiClient.POST("/api/v1/risk/options/greeks", {
        body: { book_id: params.bookId, as_of_date: params.asOfDate, commodity: params.commodity },
      });
      if (error) throw error;
      return data;
    },
  });
}

export function useRunPnlAttribution() {
  return useMutation({
    mutationFn: async (params: {
      bookId: string;
      priorDate: string;
      currentDate: string;
      commodity: Commodity;
    }) => {
      const { data, error } = await apiClient.POST("/api/v1/risk/pnl-attribution", {
        body: {
          book_id: params.bookId,
          prior_date: params.priorDate,
          current_date: params.currentDate,
          commodity: params.commodity,
        },
      });
      if (error) throw error;
      return data;
    },
  });
}
