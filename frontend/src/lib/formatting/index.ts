/** Display formatting. Every date and number on screen goes through here. */

const numberFormat = new Intl.NumberFormat("en-IN");

export function formatNumber(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : numberFormat.format(value);
}

export function formatPercent(value: number | null | undefined, digits = 0): string {
  return value === null || value === undefined ? "—" : `${value.toFixed(digits)}%`;
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  return new Date(value).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  return new Date(value).toLocaleString("en-IN", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** "3h ago", "2d ago", "just now". */
export function formatRelative(value: string | null | undefined): string {
  if (!value) return "—";
  const seconds = (Date.now() - new Date(value).getTime()) / 1000;
  if (seconds < 0) return formatDate(value);
  if (seconds < 60) return "just now";
  const minutes = seconds / 60;
  if (minutes < 60) return `${Math.floor(minutes)}m ago`;
  const hours = minutes / 60;
  if (hours < 24) return `${Math.floor(hours)}h ago`;
  const days = hours / 24;
  if (days < 30) return `${Math.floor(days)}d ago`;
  return formatDate(value);
}

export function humanize(value: string | null | undefined): string {
  if (!value) return "";
  const text = value.replace(/[_-]+/g, " ").trim().toLowerCase();
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** "₹12–18 LPA", "₹12 LPA+", or "" when the listing states nothing. */
export function formatSalary(
  min: number | null | undefined,
  max: number | null | undefined,
  currency: string | null | undefined,
): string {
  if (!min && !max) return "";
  const lakh = (value: number) => `${(value / 100_000).toFixed(value % 100_000 ? 1 : 0)}`;
  if ((currency ?? "INR") === "INR") {
    if (min && max && max !== min) return `₹${lakh(min)}–${lakh(max)} LPA`;
    return `₹${lakh((min ?? max) as number)} LPA`;
  }
  const short = (value: number) => (value >= 1000 ? `${Math.round(value / 1000)}k` : String(value));
  if (min && max && max !== min) return `${currency} ${short(min)}–${short(max)}`;
  return `${currency} ${short((min ?? max) as number)}`;
}

export function formatExperience(min: number | null | undefined, max: number | null | undefined): string {
  if (min === null || min === undefined) return "";
  if (max !== null && max !== undefined && max !== min) return `${min}–${max} yrs`;
  return `${min}+ yrs`;
}
