import type { MarketFilters } from "../types/market";

export const defaultMarketFilters: MarketFilters = {
  search: "",
  source: [],
  make: [],
  model: [],
  transmission: [],
  exteriorColor: [],
  soldOnly: false,
  page: 1,
  pageSize: 50,
  sort: "ended_at_desc",
};

function appendList(params: URLSearchParams, key: string, values: string[] | undefined): void {
  values?.filter(Boolean).forEach((value) => params.append(key, value));
}

function appendNumber(params: URLSearchParams, key: string, value: number | undefined): void {
  if (typeof value === "number" && Number.isFinite(value)) params.set(key, String(value));
}

function appendString(params: URLSearchParams, key: string, value: string | undefined): void {
  if (value?.trim()) params.set(key, value.trim());
}

export function serializeMarketFilters(filters: MarketFilters): URLSearchParams {
  const params = new URLSearchParams();
  appendString(params, "search", filters.search);
  appendList(params, "source", filters.source);
  appendList(params, "auctionStatus", filters.auctionStatus);
  appendList(params, "make", filters.make);
  appendList(params, "model", filters.model);
  appendList(params, "transmission", filters.transmission);
  appendList(params, "exteriorColor", filters.exteriorColor);
  appendNumber(params, "yearMin", filters.yearMin);
  appendNumber(params, "yearMax", filters.yearMax);
  appendNumber(params, "priceMin", filters.priceMin);
  appendNumber(params, "priceMax", filters.priceMax);
  appendNumber(params, "mileageMin", filters.mileageMin);
  appendNumber(params, "mileageMax", filters.mileageMax);
  appendString(params, "endedFrom", filters.endedFrom);
  appendString(params, "endedTo", filters.endedTo);
  if (filters.soldOnly) params.set("soldOnly", "true");
  params.set("page", String(filters.page));
  params.set("pageSize", String(filters.pageSize));
  params.set("sort", filters.sort);
  return params;
}

export function mergeMarketFilters(
  filters: MarketFilters,
  patch: Partial<MarketFilters>,
): MarketFilters {
  return { ...filters, ...patch, page: patch.page ?? 1 };
}
