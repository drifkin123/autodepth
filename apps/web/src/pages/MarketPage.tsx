import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { FilterRail } from "../components/FilterRail";
import { KpiStrip } from "../components/KpiStrip";
import { LotDetailDrawer } from "../components/LotDetailDrawer";
import { MarketCharts } from "../components/MarketCharts";
import { ResultsTable } from "../components/ResultsTable";
import { defaultMarketFilters } from "../lib/marketFilters";
import { useMarketData } from "../hooks/useMarketData";
import type { MarketFilters } from "../types/market";

export function MarketPage() {
  const [filters, setFilters] = useState<MarketFilters>({ ...defaultMarketFilters });
  const { lotId } = useParams();
  const navigate = useNavigate();
  const data = useMarketData(filters);

  const facets = data.facets.data;
  const lots = data.lots.data;
  const summary = data.summary.data;
  const priceHistory = data.priceHistory.data;
  const depreciation = data.depreciation.data;

  if (data.isLoading) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-depth-black text-depth-text">
        <p className="rounded-lg border border-depth-line bg-depth-surface px-5 py-3">Loading market data</p>
      </main>
    );
  }

  if (data.error || !facets || !lots || !summary || !priceHistory || !depreciation) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-depth-black p-6 text-depth-text">
        <section className="max-w-lg rounded-lg border border-depth-line bg-depth-surface p-6">
          <h1 className="text-xl font-semibold">Market data unavailable</h1>
          <p className="mt-3 text-depth-muted">
            Start the FastAPI service on port 8000, then refresh this page to load auction analytics.
          </p>
        </section>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-depth-black text-depth-text">
      <header className="sticky top-0 z-10 border-b border-depth-line bg-depth-black/95 backdrop-blur">
        <div className="mx-auto flex max-w-[1800px] items-center justify-between px-5 py-4">
          <div>
            <p className="text-xs uppercase tracking-[0.24em] text-depth-gold">AutoDepth</p>
            <h1 className="text-2xl font-semibold">Market Explorer</h1>
          </div>
          <div className="hidden items-center gap-2 text-xs uppercase tracking-[0.16em] text-depth-muted md:flex">
            <span className="rounded border border-depth-line px-3 py-2">{lots.total} lots</span>
            <span className="rounded border border-depth-line px-3 py-2">Sold-only charts</span>
          </div>
        </div>
      </header>

      <div className="mx-auto grid max-w-[1800px] gap-5 px-5 py-5 xl:grid-cols-[300px_1fr]">
        <FilterRail facets={facets} filters={filters} onChange={setFilters} />
        <div className="grid gap-5">
          <KpiStrip summary={summary} />
          <MarketCharts priceHistory={priceHistory} depreciation={depreciation} lots={lots.items} />
          {lots.items.length === 0 ? (
            <section className="rounded-lg border border-depth-line bg-depth-surface p-8 text-center text-depth-muted">
              No auction lots match the active filters.
            </section>
          ) : (
            <ResultsTable lots={lots.items} onSelect={(id) => navigate(`/lots/${id}`)} />
          )}
        </div>
      </div>

      <LotDetailDrawer lotId={lotId ?? null} onClose={() => navigate("/market")} />
    </main>
  );
}
