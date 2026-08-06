import { useQuery } from "@tanstack/react-query";

import { apiClient } from "../api/client";
import type { components } from "../api/generated/types";

export type BookPnlSummary = components["schemas"]["BookPnlSummary"];

export function useBookPnl(bookId: string | undefined, asOfDate: string | undefined) {
  return useQuery({
    queryKey: ["book-pnl", bookId, asOfDate],
    queryFn: async () => {
      const { data, error } = await apiClient.GET("/api/v1/positions/{book_id}/pnl", {
        params: { path: { book_id: bookId! }, query: { as_of_date: asOfDate! } },
      });
      if (error) throw error;
      return data;
    },
    enabled: Boolean(bookId && asOfDate),
  });
}
