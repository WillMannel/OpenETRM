import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "../api/client";
import type { components } from "../api/generated/types";

export type Trade = components["schemas"]["TradeRead"];
export type TradeCreate = components["schemas"]["TradeCreate"];

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
