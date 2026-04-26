import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { MarketPage } from "./MarketPage";

const fixtures = {
  facets: {
    sources: ["bring_a_trailer", "cars_and_bids"],
    makes: ["Porsche", "Audi"],
    models: ["911", "R8"],
    years: [2018, 2019],
    transmissions: ["Manual", "Automatic"],
    exteriorColors: ["White", "Blue"],
    auctionStatuses: ["sold", "reserve_not_met"],
    priceRange: { minimum: 121000, maximum: 182000 },
    mileageRange: { minimum: 9300, maximum: 18400 },
    dateRange: { minimum: "2025-01-01", maximum: "2025-03-01" },
  },
  summary: {
    totalCount: 2,
    soldCount: 1,
    medianSalePrice: 182000,
    averageSalePrice: 182000,
    lowSalePrice: 182000,
    highSalePrice: 182000,
    averageMileage: 9300,
    sellThroughRate: 0.5,
    movement30Day: null,
    movement90Day: null,
    movement365Day: null,
  },
  lots: {
    items: [
      {
        id: "lot-1",
        source: "bring_a_trailer",
        canonicalUrl: "https://example.com/gt3",
        auctionStatus: "sold",
        soldPrice: 182000,
        highBid: 182000,
        bidCount: 24,
        currency: "USD",
        endedAt: "2025-01-15T00:00:00Z",
        year: 2018,
        make: "Porsche",
        model: "911",
        trim: "GT3",
        mileage: 9300,
        exteriorColor: "White",
        transmission: "Manual",
        title: "2018 Porsche 911 GT3",
        subtitle: null,
        imageCount: 1,
      },
    ],
    total: 1,
    page: 1,
    pageSize: 50,
  },
  priceHistory: {
    buckets: [
      {
        month: "2025-01-01",
        averagePrice: 182000,
        medianPrice: 182000,
        minimumPrice: 182000,
        maximumPrice: 182000,
        count: 1,
      },
    ],
  },
  depreciation: {
    points: [
      {
        id: "lot-1",
        endedAt: "2025-01-15T00:00:00Z",
        year: 2018,
        make: "Porsche",
        model: "911",
        trim: "GT3",
        mileage: 9300,
        exteriorColor: "White",
        transmission: "Manual",
        soldPrice: 182000,
        highBid: 182000,
        auctionStatus: "sold",
        source: "bring_a_trailer",
        canonicalUrl: "https://example.com/gt3",
        title: "2018 Porsche 911 GT3",
      },
    ],
    trend: { slope: 0, intercept: 182000, points: [{ x: 20000, y: 182000 }] },
  },
};

function renderMarketPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <MarketPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("MarketPage", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/facets")) return Response.json(fixtures.facets);
        if (url.includes("/summary")) return Response.json(fixtures.summary);
        if (url.includes("/price-history")) return Response.json(fixtures.priceHistory);
        if (url.includes("/depreciation")) return Response.json(fixtures.depreciation);
        if (url.includes("/lots")) return Response.json(fixtures.lots);
        return new Response("not found", { status: 404 });
      }),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders populated market analytics", async () => {
    renderMarketPage();

    expect(screen.getByText("Loading market data")).toBeInTheDocument();
    expect(await screen.findByText("Market Explorer")).toBeInTheDocument();
    expect(screen.getAllByText("$182K").length).toBeGreaterThan(0);
    expect(screen.getByText("2018 Porsche 911 GT3")).toBeInTheDocument();
    expect(screen.getByText("Price History")).toBeInTheDocument();
    expect(screen.getByText("Mileage vs Price")).toBeInTheDocument();
  });

  it("changes query state when a make filter is selected", async () => {
    renderMarketPage();

    await screen.findByText("Market Explorer");
    await userEvent.selectOptions(screen.getByLabelText("Make"), "Porsche");

    await waitFor(() => {
      const calls = vi.mocked(fetch).mock.calls.map(([input]) => String(input));
      expect(calls.some((url) => url.includes("make=Porsche"))).toBe(true);
    });
  });
});
