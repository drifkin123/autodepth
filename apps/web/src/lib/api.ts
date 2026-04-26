import { serializeMarketFilters } from "./marketFilters";
import type {
  DepreciationResponse,
  MarketFacets,
  MarketFilters,
  MarketLotDetail,
  MarketSummary,
  PaginatedMarketLots,
  PriceHistory,
} from "../types/market";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

async function requestJson<T>(path: string, params?: URLSearchParams): Promise<T> {
  const query = params?.toString();
  const response = await fetch(`${API_BASE_URL}${path}${query ? `?${query}` : ""}`);
  if (!response.ok) {
    throw new Error(`Request failed with ${response.status}`);
  }
  return response.json() as Promise<T>;
}

function chartParams(filters: MarketFilters): URLSearchParams {
  const params = serializeMarketFilters({ ...filters, soldOnly: true, page: 1, pageSize: 200 });
  params.delete("auctionStatus");
  return params;
}

export const marketApi = {
  facets: () => requestJson<MarketFacets>("/api/market/facets"),
  lots: (filters: MarketFilters) =>
    requestJson<PaginatedMarketLots>("/api/market/lots", serializeMarketFilters(filters)),
  summary: (filters: MarketFilters) =>
    requestJson<MarketSummary>("/api/market/summary", serializeMarketFilters(filters)),
  priceHistory: (filters: MarketFilters) =>
    requestJson<PriceHistory>("/api/market/price-history", chartParams(filters)),
  depreciation: (filters: MarketFilters) =>
    requestJson<DepreciationResponse>("/api/market/depreciation", chartParams(filters)),
  lot: (id: string) => requestJson<MarketLotDetail>(`/api/market/lots/${id}`),
};
