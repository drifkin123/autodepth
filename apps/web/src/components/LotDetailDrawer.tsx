import { X } from "lucide-react";
import { useQuery } from "@tanstack/react-query";

import { marketApi } from "../lib/api";
import { formatCurrency, formatDate, formatInteger, vehicleName } from "../lib/format";

interface LotDetailDrawerProps {
  lotId: string | null;
  onClose: () => void;
}

export function LotDetailDrawer({ lotId, onClose }: LotDetailDrawerProps) {
  const detail = useQuery({
    queryKey: ["market", "lot", lotId],
    queryFn: () => marketApi.lot(lotId ?? ""),
    enabled: Boolean(lotId),
  });

  if (!lotId) return null;
  const lot = detail.data;

  return (
    <aside className="fixed inset-y-0 right-0 z-20 w-full max-w-xl border-l border-depth-line bg-depth-black shadow-2xl">
      <div className="flex items-center justify-between border-b border-depth-line p-4">
        <h2 className="text-sm font-semibold text-depth-text">Lot Detail</h2>
        <button aria-label="Close lot detail" onClick={onClose} className="text-depth-muted hover:text-depth-gold">
          <X className="h-5 w-5" />
        </button>
      </div>
      <div className="grid gap-5 overflow-y-auto p-5">
        {detail.isLoading && <p className="text-depth-muted">Loading lot detail</p>}
        {detail.isError && <p className="text-red-300">Unable to load lot detail.</p>}
        {lot && (
          <>
            <div className="aspect-[16/9] overflow-hidden rounded-lg border border-depth-line bg-depth-surface">
              {lot.images[0] ? (
                <img src={lot.images[0].imageUrl} alt="" className="h-full w-full object-cover" />
              ) : (
                <div className="flex h-full items-center justify-center text-depth-muted">No image</div>
              )}
            </div>
            <div>
              <h3 className="text-2xl font-semibold text-depth-text">
                {lot.title ?? vehicleName([lot.year, lot.make, lot.model, lot.trim])}
              </h3>
              <p className="mt-2 text-depth-muted">{lot.rawSummary ?? lot.subtitle}</p>
            </div>
            <dl className="grid grid-cols-2 gap-3 text-sm">
              {[
                ["Price", formatCurrency(lot.soldPrice ?? lot.highBid)],
                ["Mileage", formatInteger(lot.mileage)],
                ["Color", lot.exteriorColor ?? "-"],
                ["Transmission", lot.transmission ?? "-"],
                ["Engine", lot.engine ?? "-"],
                ["Ended", formatDate(lot.endedAt)],
              ].map(([label, value]) => (
                <div key={label} className="rounded-lg border border-depth-line bg-depth-surface p-3">
                  <dt className="text-xs uppercase tracking-[0.16em] text-depth-muted">{label}</dt>
                  <dd className="mt-1 text-depth-text">{value}</dd>
                </div>
              ))}
            </dl>
            <a
              href={lot.canonicalUrl}
              target="_blank"
              rel="noreferrer"
              className="rounded-md bg-depth-gold px-4 py-3 text-center text-sm font-semibold text-depth-black"
            >
              Open source listing
            </a>
            <details className="rounded-lg border border-depth-line bg-depth-surface p-4 text-sm text-depth-muted">
              <summary className="cursor-pointer text-depth-text">Data</summary>
              <pre className="mt-3 max-h-72 overflow-auto text-xs">
                {JSON.stringify({ vehicleDetails: lot.vehicleDetails, detailPayload: lot.detailPayload }, null, 2)}
              </pre>
            </details>
          </>
        )}
      </div>
    </aside>
  );
}
