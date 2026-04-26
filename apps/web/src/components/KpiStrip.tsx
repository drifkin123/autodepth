import { Activity, Gauge, TrendingUp, Trophy } from "lucide-react";

import { formatCurrency, formatInteger, formatPercent } from "../lib/format";
import type { MarketSummary } from "../types/market";

interface KpiStripProps {
  summary: MarketSummary;
}

export function KpiStrip({ summary }: KpiStripProps) {
  const cards = [
    { label: "Median Sale", value: formatCurrency(summary.medianSalePrice), icon: Trophy },
    { label: "Sold Lots", value: formatInteger(summary.soldCount), icon: Activity },
    { label: "Avg Mileage", value: formatInteger(summary.averageMileage), icon: Gauge },
    { label: "Sell Through", value: formatPercent(summary.sellThroughRate), icon: TrendingUp },
  ];

  return (
    <section className="grid gap-3 md:grid-cols-4">
      {cards.map((card) => (
        <article key={card.label} className="rounded-lg border border-depth-line bg-depth-surface p-4">
          <div className="mb-3 flex items-center justify-between text-depth-muted">
            <span className="text-xs uppercase tracking-[0.18em]">{card.label}</span>
            <card.icon className="h-4 w-4 text-depth-gold" />
          </div>
          <div className="text-2xl font-semibold text-depth-text">{card.value}</div>
        </article>
      ))}
    </section>
  );
}
