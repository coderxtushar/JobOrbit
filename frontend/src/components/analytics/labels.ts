import { humanize } from "@/lib/formatting";

const LABELS: Record<string, string> = {
  ai_ml: "AI / ML",
  genai: "GenAI",
  cloud_devops: "Cloud / DevOps",
  general_software: "General software",
  fullstack: "Full stack",
  smartrecruiters: "SmartRecruiters",
  remoteok: "RemoteOK",
  arbeitnow: "Arbeitnow",
  email_alert: "Job-alert email",
  company_site: "Company site",
  csv: "CSV",
  unscored: "Not scored",
  uncategorised: "Uncategorised",
};

/** Display label for a backend key (source, job family, band, failure category). */
export function segmentLabel(key: string): string {
  return LABELS[key] ?? humanize(key);
}

/** "3h 12m", "45m", "0m". Minutes in, a readable duration out. */
export function formatMinutes(minutes: number): string {
  const hours = Math.floor(minutes / 60);
  const rest = Math.round(minutes % 60);
  if (hours === 0) return `${rest}m`;
  return rest ? `${hours}h ${rest}m` : `${hours}h`;
}

/** A 0–1 fraction as a percentage string. */
export function formatFraction(value: number | null | undefined, digits = 1): string {
  return value === null || value === undefined ? "—" : `${(value * 100).toFixed(digits)}%`;
}
