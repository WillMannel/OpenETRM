import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "../api/client";
import type { components } from "../api/generated/types";

export type Counterparty = components["schemas"]["CounterpartyRead"];
export type Book = components["schemas"]["BookRead"];

export function useCounterparties() {
  return useQuery({
    queryKey: ["counterparties"],
    queryFn: async () => {
      const { data, error } = await apiClient.GET("/api/v1/counterparties");
      if (error) throw error;
      return data;
    },
  });
}

export function useBooks() {
  return useQuery({
    queryKey: ["books"],
    queryFn: async () => {
      const { data, error } = await apiClient.GET("/api/v1/books");
      if (error) throw error;
      return data;
    },
  });
}

export function useCreateCounterparty() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (name: string) => {
      const { data, error } = await apiClient.POST("/api/v1/counterparties", { body: { name } });
      if (error) throw error;
      return data;
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["counterparties"] }),
  });
}

export function useCreateBook() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (name: string) => {
      const { data, error } = await apiClient.POST("/api/v1/books", { body: { name } });
      if (error) throw error;
      return data;
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["books"] }),
  });
}
