/**
 * The auto-apply scope form: its zod schema, the choices it offers, and the mapping between
 * form values and the backend's `AutoApplyTargetsIn`.
 *
 * Fields the page does not edit (sources, max_discover, titles, concurrency, max_attempts)
 * are carried over from the saved preferences untouched, so building a preflight here never
 * silently resets a setting made elsewhere.
 */
import { z } from "zod";

import type { Schemas } from "@/lib/api/client";

export type TargetsIn = Schemas["AutoApplyTargetsIn"];

/** The backend accepts exactly these windows (ALLOWED_AGE_HOURS). */
export const AGE_WINDOWS = [24, 48, 72, 168, 336, 720] as const;

export function windowLabel(hours: number): string {
  return hours <= 72 ? `Last ${hours} hours` : `Last ${hours / 24} days`;
}

export const BANDS = [
  { value: "high", label: "Strong" },
  { value: "review", label: "Worth a look" },
  { value: "low", label: "Weak" },
] as const;

export const CONFIDENCE = ["low", "medium", "high"] as const;

export const ROLE_FAMILIES: { value: string; label: string }[] = [
  { value: "backend", label: "Backend" },
  { value: "frontend", label: "Frontend" },
  { value: "fullstack", label: "Full-stack" },
  { value: "data", label: "Data" },
  { value: "ai_ml", label: "AI / ML" },
  { value: "cloud_devops", label: "Cloud & DevOps" },
  { value: "mobile", label: "Mobile" },
  { value: "general_software", label: "General software" },
];

export const REMOTE_CHOICES = {
  any: "Any arrangement",
  remote_only: "Remote only",
  remote_or_hybrid: "Remote or hybrid",
  onsite_or_hybrid: "Onsite or hybrid",
} as const;

type RemoteKey = keyof typeof REMOTE_CHOICES;
const REMOTE_KEYS = Object.keys(REMOTE_CHOICES) as [RemoteKey, ...RemoteKey[]];

const whole = (label: string, min: number, max: number) =>
  z
    .number({ error: `${label} must be a number` })
    .int(`${label} must be a whole number`)
    .min(min, `${label} must be at least ${min}`)
    .max(max, `${label} must be at most ${max}`);

export const scopeSchema = z.object({
  bands: z.array(z.enum(["high", "review", "low"])).min(1, "Pick at least one match band"),
  min_score: z.number().min(0).max(100),
  max_age_hours: z
    .number()
    .refine((value) => (AGE_WINDOWS as readonly number[]).includes(value), "Pick a listed window"),
  min_confidence: z.enum(CONFIDENCE),
  role_families: z.array(z.string()),
  locations: z.array(z.string()),
  remote_preference: z.enum(REMOTE_KEYS),
  experience_tolerance_years: z
    .number({ error: "Tolerance must be a number" })
    .min(0, "Tolerance cannot be negative")
    .max(20, "Tolerance must be at most 20 years")
    .nullable(),
  platforms: z.array(z.string()),
  max_submissions: whole("Maximum submissions", 1, 500),
  daily_cap: whole("Daily cap", 1, 500).nullable(),
  excluded_companies: z.array(z.string()),
  include_cover_letter: z.boolean(),
  dry_run: z.boolean(),
});

export type ScopeValues = z.infer<typeof scopeSchema>;

/** Form values from the saved preferences. Dry run always starts on, whatever was saved. */
export function fromPreferences(saved: TargetsIn | undefined): ScopeValues {
  const bands = (saved?.bands ?? []).filter((band): band is ScopeValues["bands"][number] =>
    ["high", "review", "low"].includes(band),
  );
  const confidence = (saved?.min_confidence ?? "medium").toLowerCase();
  const remote = saved?.remote_preference ?? "any";
  const window = saved?.max_age_hours ?? 48;
  return {
    bands: bands.length ? bands : ["high", "review"],
    min_score: Math.max(0, Math.min(100, Math.round(saved?.min_score ?? 70))),
    max_age_hours: (AGE_WINDOWS as readonly number[]).includes(window) ? window : 48,
    min_confidence: (CONFIDENCE as readonly string[]).includes(confidence)
      ? (confidence as ScopeValues["min_confidence"])
      : "medium",
    role_families: saved?.role_families ?? [],
    locations: saved?.locations ?? [],
    remote_preference: remote in REMOTE_CHOICES ? (remote as RemoteKey) : "any",
    experience_tolerance_years:
      saved?.experience_tolerance_years === undefined ? 1 : saved.experience_tolerance_years,
    platforms: saved?.platforms ?? [],
    max_submissions: Math.max(1, saved?.max_submissions ?? 100),
    daily_cap: saved?.daily_cap ?? null,
    excluded_companies: saved?.excluded_companies ?? [],
    include_cover_letter: saved?.include_cover_letter ?? true,
    dry_run: true,
  };
}

/** The request body: saved preferences, overlaid with the form, plus the approved ids. */
export function toTargets(
  values: ScopeValues,
  saved: TargetsIn | undefined,
  approvedJobIds: number[],
): TargetsIn {
  return {
    sources: saved?.sources ?? [],
    max_discover: saved?.max_discover ?? 200,
    titles: saved?.titles ?? [],
    concurrency: saved?.concurrency ?? 4,
    max_attempts: saved?.max_attempts ?? 2,
    ...values,
    approved_job_ids: approvedJobIds,
  };
}

/** A stable key for "is this the scope the preflight was built for?". */
export function scopeKey(targets: TargetsIn): string {
  const sorted = Object.keys(targets)
    .sort()
    .map((key) => {
      const value = targets[key as keyof TargetsIn];
      return [key, Array.isArray(value) ? [...value].map(String).sort() : value];
    });
  return JSON.stringify(sorted);
}

/** `?jobs=1,2,3` from Job discovery: positive integer ids, de-duplicated, at most 500. */
export function parseJobIds(raw: string | null): number[] {
  if (!raw) return [];
  const ids = raw
    .split(",")
    .map((part) => Number(part.trim()))
    .filter((id) => Number.isInteger(id) && id > 0);
  return Array.from(new Set(ids)).slice(0, 500);
}
