import { ExternalLink } from "lucide-react";

import { formatCurrency, formatDate, formatInteger, vehicleName } from "../lib/format";
import type { MarketLot } from "../types/market";

interface ResultsTableProps {
  lots: MarketLot[];
  onSelect: (id: string) => void;
}

export function ResultsTable({ lots, onSelect }: ResultsTableProps) {
  return (
    <section className="rounded-lg border border-depth-line bg-depth-surface p-4">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-depth-text">Recent Results</h2>
        <span className="text-xs uppercase tracking-[0.18em] text-depth-muted">{lots.length} visible</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[900px] text-left text-sm">
          <thead className="text-xs uppercase tracking-[0.16em] text-depth-muted">
            <tr className="border-b border-depth-line">
              <th className="px-3 py-3">Vehicle</th>
              <th className="px-3 py-3">Price</th>
              <th className="px-3 py-3">Mileage</th>
              <th className="px-3 py-3">Color</th>
              <th className="px-3 py-3">Transmission</th>
              <th className="px-3 py-3">Source</th>
              <th className="px-3 py-3">Status</th>
              <th className="px-3 py-3">Ended</th>
              <th className="px-3 py-3">Link</th>
            </tr>
          </thead>
          <tbody>
            {lots.map((lot) => (
              <tr
                key={lot.id}
                className="cursor-pointer border-b border-depth-line/70 text-depth-text transition hover:bg-depth-panel"
                onClick={() => onSelect(lot.id)}
              >
                <td className="px-3 py-3 font-medium">
                  {lot.title ?? vehicleName([lot.year, lot.make, lot.model, lot.trim])}
                </td>
                <td className="px-3 py-3">{formatCurrency(lot.soldPrice ?? lot.highBid)}</td>
                <td className="px-3 py-3">{formatInteger(lot.mileage)}</td>
                <td className="px-3 py-3">{lot.exteriorColor ?? "-"}</td>
                <td className="px-3 py-3">{lot.transmission ?? "-"}</td>
                <td className="px-3 py-3">{lot.source.replaceAll("_", " ")}</td>
                <td className="px-3 py-3">
                  <span className="rounded border border-depth-line px-2 py-1 text-xs">
                    {lot.auctionStatus.replaceAll("_", " ")}
                  </span>
                </td>
                <td className="px-3 py-3">{formatDate(lot.endedAt)}</td>
                <td className="px-3 py-3">
                  <a
                    href={lot.canonicalUrl}
                    className="inline-flex text-depth-gold"
                    target="_blank"
                    rel="noreferrer"
                    onClick={(event) => event.stopPropagation()}
                  >
                    <ExternalLink className="h-4 w-4" />
                  </a>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
