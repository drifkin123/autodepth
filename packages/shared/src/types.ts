// ─── Core domain types ────────────────────────────────────────────────────────

export interface Car {
  id: string
  make: string
  model: string
  trim: string
  yearStart: number
  yearEnd: number | null        // null = still in production
  productionCount: number | null
  engine: string
  isNaturallyAspirated: boolean
  msrpOriginal: number          // USD
  notes: string | null
  createdAt: string             // ISO timestamp
}

// ─── Vehicle sales / listings ─────────────────────────────────────────────────

export type SaleSource =
  | 'bring_a_trailer'
  | 'cars_and_bids'
  | 'rm_sotheby'
  | 'cars_com'
  | 'dealer'
  | 'private_seller'

export type SaleType = 'auction' | 'listing' | 'dealer' | 'private'

export type AuctionStatus = 'sold' | 'reserve_not_met' | 'withdrawn' | 'unknown'

export interface VehicleSale {
  id: string
  carId: string
  source: SaleSource
  sourceUrl: string
  saleType: SaleType
  sourceAuctionId: string | null
  auctionStatus: AuctionStatus | null
  year: number                  // model year of the specific unit
  mileage: number | null
  color: string | null
  askingPrice: number           // always present (listed/opening price)
  soldPrice: number | null      // confirmed final sale price; NULL for listings
                                // NOTE: asking vs sold diverge significantly —
                                // soldPrice is authoritative for market value
  highBid: number | null
  bidCount: number | null
  title: string | null
  subtitle: string | null
  imageCount: number
  vehicleDetails: Record<string, unknown>
  isSold: boolean
  listedAt: string              // ISO timestamp
  soldAt: string | null         // ISO timestamp; null if not a confirmed sale
  conditionNotes: string | null
  options: Record<string, unknown>
}

export interface AuctionImage {
  id: string
  vehicleSaleId: string
  source: SaleSource
  sourceUrl: string
  imageUrl: string
  position: number
  caption: string | null
  width: number | null
  height: number | null
  createdAt: string
}

// ─── Price history ─────────────────────────────────────────────────────────────

/** Aggregated monthly price bucket for charting */
export interface PricePoint {
  date: string                  // "YYYY-MM" month bucket
  avgSoldPrice: number | null   // avg of soldPrice where isSold=true
  avgAskingPrice: number | null // avg of askingPrice across all listings
  soldCount: number
  listingCount: number
}

// ─── Depreciation predictions ──────────────────────────────────────────────────

export interface PricePrediction {
  id: string
  carId: string
  modelVersion: string
  predictedFor: string          // "YYYY-MM-DD"
  predictedPrice: number
  confidenceLow: number
  confidenceHigh: number
  generatedAt: string
}

// ─── Buy window ────────────────────────────────────────────────────────────────

export type BuyWindowStatus =
  | 'depreciating_fast' // 🔴 still dropping meaningfully
  | 'near_floor'        // 🟡 approaching the predicted floor
  | 'at_floor'          // 🟢 at or past the floor — optimal buy zone
  | 'appreciating'      // ⬆️ values rising (collectible/limited)

// ─── Watchlist ─────────────────────────────────────────────────────────────────

export interface WatchlistItem {
  id: string
  userId: string
  carId: string
  car?: Car
  targetPrice: number | null    // user's budget / target buy price
  notes: string | null
  addedAt: string
}

/** WatchlistItem enriched with live market data for the Garage view */
export interface WatchlistItemWithStatus extends WatchlistItem {
  car: Car
  currentEstimatedValue: number | null
  valueDeltaSinceAdded: number | null  // USD change since addedAt
  buyWindowStatus: BuyWindowStatus | null
}

// ─── API response shapes ───────────────────────────────────────────────────────

export interface ApiError {
  error: string
  detail?: string
}

export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  pageSize: number
}

export interface CarSalesResponse {
  car: Car
  sales: PaginatedResponse<VehicleSale>
}

export interface PriceHistoryResponse {
  car: Car
  priceHistory: PricePoint[]
}

export interface PredictionResponse {
  car: Car
  predictions: PricePrediction[]
  buyWindowStatus: BuyWindowStatus
  buyWindowDate: string | null  // predicted optimal buy date
  summary: string               // plain-English explanation
}

export interface CompareResponse {
  cars: Car[]
  priceHistories: Record<string, PricePoint[]>   // keyed by carId
  predictions: Record<string, PricePrediction[]> // keyed by carId
  aiSummary: string                               // Claude-generated comparison
}
