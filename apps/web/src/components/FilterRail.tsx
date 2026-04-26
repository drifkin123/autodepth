import { Filter, RotateCcw, Search } from "lucide-react";

import { defaultMarketFilters, mergeMarketFilters } from "../lib/marketFilters";
import type { MarketFacets, MarketFilters } from "../types/market";

interface FilterRailProps {
  facets: MarketFacets;
  filters: MarketFilters;
  onChange: (filters: MarketFilters) => void;
}

function selectedValues(select: HTMLSelectElement): string[] {
  return Array.from(select.selectedOptions).map((option) => option.value);
}

interface MultiSelectProps {
  label: string;
  values: string[];
  selected: string[];
  onChange: (values: string[]) => void;
}

function MultiSelect({ label, values, selected, onChange }: MultiSelectProps) {
  return (
    <label className="grid gap-2 text-xs uppercase tracking-[0.18em] text-depth-muted">
      {label}
      <select
        aria-label={label}
        className="min-h-24 rounded-md border border-depth-line bg-depth-black p-2 text-sm normal-case tracking-normal text-depth-text outline-none focus:border-depth-gold"
        multiple
        value={selected}
        onChange={(event) => onChange(selectedValues(event.currentTarget))}
      >
        {values.map((value) => (
          <option key={value} value={value}>
            {value.replaceAll("_", " ")}
          </option>
        ))}
      </select>
    </label>
  );
}

export function FilterRail({ facets, filters, onChange }: FilterRailProps) {
  const update = (patch: Partial<MarketFilters>) => onChange(mergeMarketFilters(filters, patch));

  return (
    <aside className="rounded-lg border border-depth-line bg-depth-surface p-4">
      <div className="mb-5 flex items-center justify-between">
        <div className="flex items-center gap-2 text-sm font-semibold text-depth-text">
          <Filter className="h-4 w-4 text-depth-gold" />
          Filters
        </div>
        <button
          className="rounded-md border border-depth-line p-2 text-depth-muted transition hover:border-depth-gold hover:text-depth-gold"
          aria-label="Reset filters"
          onClick={() => onChange(defaultMarketFilters)}
        >
          <RotateCcw className="h-4 w-4" />
        </button>
      </div>

      <div className="grid gap-4">
        <label className="grid gap-2 text-xs uppercase tracking-[0.18em] text-depth-muted">
          Search
          <span className="flex items-center gap-2 rounded-md border border-depth-line bg-depth-black px-3">
            <Search className="h-4 w-4 text-depth-muted" />
            <input
              className="h-10 w-full bg-transparent text-sm normal-case tracking-normal text-depth-text outline-none"
              value={filters.search}
              placeholder="GT3, R8, manual..."
              onChange={(event) => update({ search: event.target.value })}
            />
          </span>
        </label>

        <MultiSelect label="Make" values={facets.makes} selected={filters.make} onChange={(make) => update({ make })} />
        <MultiSelect label="Model" values={facets.models} selected={filters.model} onChange={(model) => update({ model })} />
        <MultiSelect label="Source" values={facets.sources} selected={filters.source} onChange={(source) => update({ source })} />
        <MultiSelect
          label="Transmission"
          values={facets.transmissions}
          selected={filters.transmission}
          onChange={(transmission) => update({ transmission })}
        />
        <MultiSelect
          label="Color"
          values={facets.exteriorColors}
          selected={filters.exteriorColor}
          onChange={(exteriorColor) => update({ exteriorColor })}
        />

        <div className="grid grid-cols-2 gap-3">
          <input
            aria-label="Year minimum"
            className="h-10 rounded-md border border-depth-line bg-depth-black px-3 text-sm text-depth-text outline-none"
            placeholder="Year min"
            type="number"
            onChange={(event) => update({ yearMin: event.target.value ? Number(event.target.value) : undefined })}
          />
          <input
            aria-label="Year maximum"
            className="h-10 rounded-md border border-depth-line bg-depth-black px-3 text-sm text-depth-text outline-none"
            placeholder="Year max"
            type="number"
            onChange={(event) => update({ yearMax: event.target.value ? Number(event.target.value) : undefined })}
          />
        </div>
      </div>
    </aside>
  );
}
