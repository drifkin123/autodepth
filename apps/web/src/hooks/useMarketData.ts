import { useQuery } from "@tanstack/react-query";

import { marketApi } from "../lib/api";
import type { MarketFilters } from "../types/market";

export function useMarketData(filters: MarketFilters) {
  const queryKey = ["market", filters];
  const facets = useQuery({ queryKey: ["market", "facets"], queryFn: marketApi.facets });
  const lots = useQuery({ queryKey: [...queryKey, "lots"], queryFn: () => marketApi.lots(filters) });
  const summary = useQuery({
    queryKey: [...queryKey, "summary"],
    queryFn: () => marketApi.summary(filters),
  });
  const priceHistory = useQuery({
    queryKey: [...queryKey, "price-history"],
    queryFn: () => marketApi.priceHistory(filters),
  });
  const depreciation = useQuery({
    queryKey: [...queryKey, "depreciation"],
    queryFn: () => marketApi.depreciation(filters),
  });
  const isLoading =
    facets.isLoading ||
    lots.isLoading ||
    summary.isLoading ||
    priceHistory.isLoading ||
    depreciation.isLoading;
  const error =
    facets.error ?? lots.error ?? summary.error ?? priceHistory.error ?? depreciation.error ?? null;
  return { facets, lots, summary, priceHistory, depreciation, isLoading, error };
}
