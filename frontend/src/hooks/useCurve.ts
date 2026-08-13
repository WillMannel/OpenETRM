import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "../api/client";
import type { components } from "../api/generated/types";
import type { Commodity } from "./useSelection";

export type ForwardCurve = components["schemas"]["ForwardCurveRead"];

export function useBuildCurve() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (params: { asOfDate: string; commodity: Commodity }) => {
      const { data, error } = await apiClient.POST("/api/v1/curves/build", {
        body: { as_of_date: params.asOfDate, commodity: params.commodity },
      });
      if (error) throw error;
      return data;
    },
    onSuccess: (curve) => {
      queryClient.setQueryData(["curve", curve.id], curve);
    },
  });
}

export function useCurve(curveId: string | undefined) {
  return useQuery({
    queryKey: ["curve", curveId],
    queryFn: async () => {
      const { data, error } = await apiClient.GET("/api/v1/curves/{curve_id}", {
        params: { path: { curve_id: curveId! } },
      });
      if (error) throw error;
      return data;
    },
    enabled: Boolean(curveId),
  });
}
