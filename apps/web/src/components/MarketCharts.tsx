import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { formatCurrency } from "../lib/format";
import type { DepreciationResponse, MarketLot, PriceHistory } from "../types/market";

interface MarketChartsProps {
  priceHistory: PriceHistory;
  depreciation: DepreciationResponse;
  lots: MarketLot[];
}

function ChartPanel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-depth-line bg-depth-surface p-4">
      <h2 className="mb-4 text-sm font-semibold text-depth-text">{title}</h2>
      <div className="h-64">{children}</div>
    </section>
  );
}

function priceBuckets(lots: MarketLot[]) {
  const counts = new Map<string, number>();
  lots.forEach((lot) => {
    const value = lot.soldPrice ?? lot.highBid;
    if (!value) return;
    const bucket = `${Math.floor(value / 50_000) * 50}K`;
    counts.set(bucket, (counts.get(bucket) ?? 0) + 1);
  });
  return Array.from(counts, ([bucket, count]) => ({ bucket, count }));
}

export function MarketCharts({ priceHistory, depreciation, lots }: MarketChartsProps) {
  const mileageData = lots
    .filter((lot) => lot.mileage && (lot.soldPrice ?? lot.highBid))
    .map((lot) => ({ mileage: lot.mileage, price: lot.soldPrice ?? lot.highBid, name: lot.title }));

  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <ChartPanel title="Price History">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={priceHistory.buckets}>
            <CartesianGrid stroke="#2A2A2A" />
            <XAxis dataKey="month" tick={{ fill: "#888" }} />
            <YAxis tick={{ fill: "#888" }} tickFormatter={formatCurrency} />
            <Tooltip contentStyle={{ background: "#141414", border: "1px solid #2A2A2A" }} />
            <Line dataKey="medianPrice" stroke="#E8D5A3" strokeWidth={2} dot={false} />
            <Line dataKey="averagePrice" stroke="#8DD3C7" strokeWidth={2} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </ChartPanel>

      <ChartPanel title="Depreciation Scatter">
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart>
            <CartesianGrid stroke="#2A2A2A" />
            <XAxis dataKey="year" name="Model year" tick={{ fill: "#888" }} />
            <YAxis dataKey="soldPrice" tick={{ fill: "#888" }} tickFormatter={formatCurrency} />
            <Tooltip contentStyle={{ background: "#141414", border: "1px solid #2A2A2A" }} />
            <Scatter data={depreciation.points} fill="#E8D5A3" />
          </ScatterChart>
        </ResponsiveContainer>
      </ChartPanel>

      <ChartPanel title="Price Distribution">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={priceBuckets(lots)}>
            <CartesianGrid stroke="#2A2A2A" />
            <XAxis dataKey="bucket" tick={{ fill: "#888" }} />
            <YAxis tick={{ fill: "#888" }} />
            <Tooltip contentStyle={{ background: "#141414", border: "1px solid #2A2A2A" }} />
            <Bar dataKey="count">
              {priceBuckets(lots).map((entry, index) => (
                <Cell key={entry.bucket} fill={index % 2 ? "#8DD3C7" : "#E8D5A3"} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </ChartPanel>

      <ChartPanel title="Mileage vs Price">
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart>
            <CartesianGrid stroke="#2A2A2A" />
            <XAxis dataKey="mileage" tick={{ fill: "#888" }} />
            <YAxis dataKey="price" tick={{ fill: "#888" }} tickFormatter={formatCurrency} />
            <Tooltip contentStyle={{ background: "#141414", border: "1px solid #2A2A2A" }} />
            <Scatter data={mileageData} fill="#80B1D3" />
          </ScatterChart>
        </ResponsiveContainer>
      </ChartPanel>
    </div>
  );
}
