import { describe, expect, it } from "vitest";

import { serializeMarketFilters } from "./marketFilters";

describe("serializeMarketFilters", () => {
  it("serializes filter state into backend query params", () => {
    const params = serializeMarketFilters({
      search: "gt3",
      source: ["bring_a_trailer", "cars_and_bids"],
      make: ["Porsche"],
      model: ["911"],
      yearMin: 2016,
      yearMax: 2024,
      transmission: ["Manual"],
      exteriorColor: ["White"],
      priceMin: 100000,
      priceMax: 250000,
      mileageMin: 0,
      mileageMax: 25000,
      endedFrom: "2024-01-01",
      endedTo: "2025-12-31",
      soldOnly: true,
      page: 2,
      pageSize: 25,
      sort: "price_desc",
    });

    expect(params.getAll("source")).toEqual(["bring_a_trailer", "cars_and_bids"]);
    expect(params.get("auctionStatus")).toBeNull();
    expect(params.get("make")).toBe("Porsche");
    expect(params.get("yearMin")).toBe("2016");
    expect(params.get("exteriorColor")).toBe("White");
    expect(params.get("soldOnly")).toBe("true");
    expect(params.get("pageSize")).toBe("25");
  });

  it("omits empty filters and false toggles", () => {
    const params = serializeMarketFilters({
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
    });

    expect(params.toString()).toBe("page=1&pageSize=50&sort=ended_at_desc");
  });
});
