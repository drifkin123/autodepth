export function formatCurrency(value: number | null | undefined): string {
  if (value == null) return "-";
  if (Math.abs(value) >= 1_000_000) return `$${(value / 1_000_000).toFixed(1)}M`;
  if (Math.abs(value) >= 1_000) return `$${Math.round(value / 1_000)}K`;
  return `$${value.toLocaleString()}`;
}

export function formatInteger(value: number | null | undefined): string {
  return value == null ? "-" : value.toLocaleString();
}

export function formatPercent(value: number | null | undefined): string {
  if (value == null) return "-";
  return `${(value * 100).toFixed(0)}%`;
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "-";
  return new Intl.DateTimeFormat("en", { month: "short", day: "numeric", year: "numeric" }).format(
    new Date(value),
  );
}

export function vehicleName(parts: Array<number | string | null>): string {
  return parts.filter(Boolean).join(" ") || "Unknown vehicle";
}
