export interface NumericRange {
  minimum: number | null;
  maximum: number | null;
}

export interface DateRange {
  minimum: string | null;
  maximum: string | null;
}

export interface MarketFacets {
  sources: string[];
  makes: string[];
  models: string[];
  years: number[];
  transmissions: string[];
  exteriorColors: string[];
  auctionStatuses: string[];
  priceRange: NumericRange;
  mileageRange: NumericRange;
  dateRange: DateRange;
}

export interface MarketFilters {
  search: string;
  source: string[];
  auctionStatus?: string[];
  make: string[];
  model: string[];
  yearMin?: number;
  yearMax?: number;
  transmission: string[];
  exteriorColor: string[];
  priceMin?: number;
  priceMax?: number;
  mileageMin?: number;
  mileageMax?: number;
  endedFrom?: string;
  endedTo?: string;
  soldOnly: boolean;
  page: number;
  pageSize: number;
  sort: string;
}

export interface MarketLot {
  id: string;
  source: string;
  canonicalUrl: string;
  auctionStatus: string;
  soldPrice: number | null;
  highBid: number | null;
  bidCount: number | null;
  currency: string;
  endedAt: string | null;
  year: number | null;
  make: string | null;
  model: string | null;
  trim: string | null;
  mileage: number | null;
  exteriorColor: string | null;
  transmission: string | null;
  title: string | null;
  subtitle: string | null;
  imageCount: number;
}

export interface PaginatedMarketLots {
  items: MarketLot[];
  total: number;
  page: number;
  pageSize: number;
}

export interface MarketSummary {
  totalCount: number;
  soldCount: number;
  medianSalePrice: number | null;
  averageSalePrice: number | null;
  lowSalePrice: number | null;
  highSalePrice: number | null;
  averageMileage: number | null;
  sellThroughRate: number | null;
  movement30Day: number | null;
  movement90Day: number | null;
  movement365Day: number | null;
}

export interface PriceHistoryBucket {
  month: string;
  averagePrice: number;
  medianPrice: number;
  minimumPrice: number;
  maximumPrice: number;
  count: number;
}

export interface PriceHistory {
  buckets: PriceHistoryBucket[];
}

export interface DepreciationPoint {
  id: string;
  endedAt: string;
  year: number | null;
  make: string | null;
  model: string | null;
  trim: string | null;
  mileage: number | null;
  exteriorColor: string | null;
  transmission: string | null;
  soldPrice: number;
  highBid: number | null;
  auctionStatus: string;
  source: string;
  canonicalUrl: string;
  title: string | null;
}

export interface DepreciationResponse {
  points: DepreciationPoint[];
  trend: { slope: number; intercept: number; points: { x: number; y: number }[] } | null;
}

export interface MarketImage {
  id: string;
  imageUrl: string;
  position: number;
  caption: string | null;
}

export interface MarketLotDetail extends MarketLot {
  sourceAuctionId: string | null;
  listedAt: string | null;
  vin: string | null;
  interiorColor: string | null;
  drivetrain: string | null;
  engine: string | null;
  bodyStyle: string | null;
  location: string | null;
  seller: string | null;
  rawSummary: string | null;
  vehicleDetails: Record<string, unknown>;
  listPayload: Record<string, unknown>;
  detailPayload: Record<string, unknown>;
  images: MarketImage[];
}
