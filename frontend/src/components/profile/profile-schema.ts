/**
 * The profile editor's form model.
 *
 * The form keeps numbers as strings so an empty box can mean "not stated" rather than zero,
 * and tri-state answers (relocation, sponsorship) as "unset" | "yes" | "no" so an unanswered
 * question is never sent as false. Limits mirror app/schemas/profile.py; the backend stays
 * the authority and its field errors are shown next to the same fields.
 */
import { z } from "zod";

import type { Schemas } from "@/lib/api/client";

export const EXPERIENCE_LEVELS = ["fresher", "junior", "mid", "senior", "lead"] as const;
export const WORK_ARRANGEMENTS = ["onsite", "hybrid", "remote"] as const;
export const EMPLOYMENT_TYPES = ["full_time", "part_time", "internship", "contract", "temporary"] as const;
export const CURRENCIES = ["INR", "USD", "EUR", "GBP", "SGD", "AED", "CAD", "AUD"] as const;

const triState = z.enum(["unset", "yes", "no"]);
export type TriState = z.infer<typeof triState>;

function numberText({
  label,
  min,
  max,
  integer = false,
  optional = false,
}: {
  label: string;
  min: number;
  max: number;
  integer?: boolean;
  optional?: boolean;
}) {
  return z.string().superRefine((raw, ctx) => {
    const value = raw.trim();
    if (value === "") {
      if (!optional) ctx.addIssue({ code: "custom", message: `${label} is required.` });
      return;
    }
    const number = Number(value);
    if (!Number.isFinite(number)) {
      ctx.addIssue({ code: "custom", message: "Enter a number." });
      return;
    }
    if (integer && !Number.isInteger(number)) {
      ctx.addIssue({ code: "custom", message: "Enter a whole number." });
      return;
    }
    if (number < min || number > max) {
      ctx.addIssue({ code: "custom", message: `${label} must be between ${min} and ${max.toLocaleString("en-IN")}.` });
    }
  });
}

const urlish = (value: string) => value.trim() === "" || /^https?:\/\/\S+$/i.test(value.trim());

const educationEntry = z.object({
  degree: z.string().max(200),
  institution: z.string().max(200),
  field_of_study: z.string().max(200),
  start_year: z.string().max(20),
  end_year: z.string().max(20),
  grade: z.string().max(50),
});

const projectEntry = z.object({
  name: z.string().trim().min(1, "Give the project a name, or remove it.").max(200),
  description: z.string().max(2000),
  technologies: z.array(z.string()),
  url: z.string().refine(urlish, "Use a full URL starting with https://"),
});

export const profileSchema = z
  .object({
    full_name: z.string().max(200, "At most 200 characters."),
    email: z
      .string()
      .max(320)
      .refine((value) => value.trim() === "" || /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value.trim()), "Enter a valid email address."),
    phone: z.string().max(50, "At most 50 characters."),
    links: z.array(z.string()).refine((items) => items.every(urlish), "Each link should be a full URL starting with https://"),
    headline: z.string().max(300, "At most 300 characters."),
    experience_level: z.enum(EXPERIENCE_LEVELS),
    years_experience: numberText({ label: "Years of experience", min: 0, max: 60 }),
    target_titles: z.array(z.string()),
    technical_skills: z.array(z.string()),
    soft_skills: z.array(z.string()),
    education: z.array(educationEntry),
    graduation_date: z.string().max(20, "At most 20 characters."),
    projects: z.array(projectEntry),
    certifications: z.array(z.string()),
    preferred_locations: z.array(z.string()),
    work_arrangements: z.array(z.enum(WORK_ARRANGEMENTS)),
    employment_types: z.array(z.enum(EMPLOYMENT_TYPES)),
    open_to_relocation: triState,
    preferred_companies: z.array(z.string()),
    preferred_industries: z.array(z.string()),
    salary_expectation_min: numberText({ label: "Minimum", min: 0, max: 1_000_000_000, integer: true, optional: true }),
    salary_expectation_max: numberText({ label: "Maximum", min: 0, max: 1_000_000_000, integer: true, optional: true }),
    salary_currency: z.string().trim().min(1, "Pick a currency.").max(10),
    notice_period_days: numberText({ label: "Notice period", min: 0, max: 365, integer: true, optional: true }),
    work_authorization: z.string().max(200, "At most 200 characters."),
    requires_sponsorship: triState,
    excluded_companies: z.array(z.string()),
    excluded_keywords: z.array(z.string()),
    minimum_match_score: numberText({ label: "Minimum match score", min: 0, max: 100 }),
    max_job_age_days: numberText({ label: "Maximum job age", min: 1, max: 365, integer: true }),
    max_required_experience_years: numberText({ label: "Maximum required experience", min: 0, max: 40, optional: true }),
    requires_india_work_eligibility: z.boolean(),
  })
  .superRefine((values, ctx) => {
    const low = values.salary_expectation_min.trim();
    const high = values.salary_expectation_max.trim();
    if (low && high && Number(low) > Number(high)) {
      ctx.addIssue({
        code: "custom",
        path: ["salary_expectation_max"],
        message: "The maximum cannot be lower than the minimum.",
      });
    }
  });

export type ProfileFormValues = z.infer<typeof profileSchema>;
export type ProfileFieldName = keyof ProfileFormValues;

const str = (value: unknown) => (value === null || value === undefined ? "" : String(value));
const num = (value: number | null | undefined) => (value === null || value === undefined ? "" : String(value));
const tri = (value: boolean | null | undefined): TriState => (value === null || value === undefined ? "unset" : value ? "yes" : "no");
const fromTri = (value: TriState): boolean | null => (value === "unset" ? null : value === "yes");
const toNumber = (value: string): number | null => (value.trim() === "" ? null : Number(value.trim()));

function pick<T extends string>(allowed: readonly T[], values: string[]): T[] {
  return values.filter((value): value is T => (allowed as readonly string[]).includes(value));
}

export function toFormValues(profile: Schemas["ProfileRead"]): ProfileFormValues {
  const level = (EXPERIENCE_LEVELS as readonly string[]).includes(profile.experience_level)
    ? (profile.experience_level as ProfileFormValues["experience_level"])
    : "fresher";
  const education = (profile.education as Record<string, unknown>[]).map((entry) => ({
    degree: str(entry.degree),
    institution: str(entry.institution),
    field_of_study: str(entry.field_of_study),
    start_year: str(entry.start_year),
    end_year: str(entry.end_year),
    grade: str(entry.grade),
  }));
  const projects = (profile.projects as Record<string, unknown>[]).map((entry) => ({
    name: str(entry.name),
    description: str(entry.description),
    technologies: Array.isArray(entry.technologies) ? entry.technologies.map(String) : [],
    url: str(entry.url),
  }));
  return {
    full_name: profile.full_name ?? "",
    email: profile.email ?? "",
    phone: profile.phone ?? "",
    links: profile.links ?? [],
    headline: profile.headline ?? "",
    experience_level: level,
    years_experience: num(profile.years_experience),
    target_titles: profile.target_titles ?? [],
    technical_skills: profile.technical_skills ?? [],
    soft_skills: profile.soft_skills ?? [],
    education,
    graduation_date: profile.graduation_date ?? "",
    projects,
    certifications: profile.certifications ?? [],
    preferred_locations: profile.preferred_locations ?? [],
    work_arrangements: pick(WORK_ARRANGEMENTS, profile.work_arrangements ?? []),
    employment_types: pick(EMPLOYMENT_TYPES, profile.employment_types ?? []),
    open_to_relocation: tri(profile.open_to_relocation),
    preferred_companies: profile.preferred_companies ?? [],
    preferred_industries: profile.preferred_industries ?? [],
    salary_expectation_min: num(profile.salary_expectation_min),
    salary_expectation_max: num(profile.salary_expectation_max),
    salary_currency: profile.salary_currency || "INR",
    notice_period_days: num(profile.notice_period_days),
    work_authorization: profile.work_authorization ?? "",
    requires_sponsorship: tri(profile.requires_sponsorship),
    excluded_companies: profile.excluded_companies ?? [],
    excluded_keywords: profile.excluded_keywords ?? [],
    minimum_match_score: num(profile.minimum_match_score),
    max_job_age_days: num(profile.max_job_age_days),
    max_required_experience_years: num(profile.max_required_experience_years),
    requires_india_work_eligibility: Boolean(profile.requires_india_work_eligibility),
  };
}

/** The full update body for the form's values. Blank sensitive answers are sent as null. */
export function toPayload(values: ProfileFormValues): Schemas["ProfileUpdate"] {
  const clean = (items: string[]) => items.map((item) => item.trim()).filter(Boolean);
  return {
    full_name: values.full_name.trim(),
    email: values.email.trim(),
    phone: values.phone.trim(),
    links: clean(values.links),
    headline: values.headline.trim(),
    experience_level: values.experience_level,
    years_experience: toNumber(values.years_experience) ?? 0,
    target_titles: clean(values.target_titles),
    technical_skills: clean(values.technical_skills),
    soft_skills: clean(values.soft_skills),
    education: values.education.map((entry) => ({
      degree: entry.degree.trim(),
      institution: entry.institution.trim(),
      field_of_study: entry.field_of_study.trim(),
      start_year: entry.start_year.trim(),
      end_year: entry.end_year.trim(),
      grade: entry.grade.trim(),
    })),
    graduation_date: values.graduation_date.trim() || null,
    projects: values.projects.map((entry) => ({
      name: entry.name.trim(),
      description: entry.description.trim(),
      technologies: clean(entry.technologies),
      url: entry.url.trim(),
    })),
    certifications: clean(values.certifications),
    preferred_locations: clean(values.preferred_locations),
    work_arrangements: values.work_arrangements,
    employment_types: values.employment_types,
    open_to_relocation: fromTri(values.open_to_relocation),
    preferred_companies: clean(values.preferred_companies),
    preferred_industries: clean(values.preferred_industries),
    salary_expectation_min: toNumber(values.salary_expectation_min),
    salary_expectation_max: toNumber(values.salary_expectation_max),
    salary_currency: values.salary_currency.trim().toUpperCase(),
    notice_period_days: toNumber(values.notice_period_days),
    work_authorization: values.work_authorization.trim() || null,
    requires_sponsorship: fromTri(values.requires_sponsorship),
    excluded_companies: clean(values.excluded_companies),
    excluded_keywords: clean(values.excluded_keywords),
    minimum_match_score: toNumber(values.minimum_match_score),
    max_job_age_days: toNumber(values.max_job_age_days),
    max_required_experience_years: toNumber(values.max_required_experience_years),
    requires_india_work_eligibility: values.requires_india_work_eligibility,
  };
}

// --------------------------------------------------------------------------------------
// Sections and completeness
// --------------------------------------------------------------------------------------

export type SectionId = "resumes" | "identity" | "experience" | "background" | "preferences" | "compensation" | "filters";

/** Which section each form field lives in, so a failed save can open the right tab. */
export const FIELD_SECTION: Record<ProfileFieldName, Exclude<SectionId, "resumes">> = {
  full_name: "identity",
  email: "identity",
  phone: "identity",
  links: "identity",
  headline: "identity",
  experience_level: "experience",
  years_experience: "experience",
  target_titles: "experience",
  technical_skills: "experience",
  soft_skills: "experience",
  education: "background",
  graduation_date: "background",
  projects: "background",
  certifications: "background",
  preferred_locations: "preferences",
  work_arrangements: "preferences",
  employment_types: "preferences",
  open_to_relocation: "preferences",
  preferred_companies: "preferences",
  preferred_industries: "preferences",
  salary_expectation_min: "compensation",
  salary_expectation_max: "compensation",
  salary_currency: "compensation",
  notice_period_days: "compensation",
  work_authorization: "compensation",
  requires_sponsorship: "compensation",
  excluded_companies: "filters",
  excluded_keywords: "filters",
  minimum_match_score: "filters",
  max_job_age_days: "filters",
  max_required_experience_years: "filters",
  requires_india_work_eligibility: "filters",
};

export interface CompletenessItem {
  key: string;
  label: string;
  section: Exclude<SectionId, "resumes">;
  sensitive?: boolean;
  filled: (values: ProfileFormValues) => boolean;
}

const has = (value: string) => value.trim() !== "";

/**
 * What "complete" means here: each item is a field an application or the matcher reads.
 * It is a count of filled fields, nothing more; it does not judge the content.
 */
export const COMPLETENESS: CompletenessItem[] = [
  { key: "full_name", label: "Full name", section: "identity", filled: (v) => has(v.full_name) },
  { key: "email", label: "Email", section: "identity", filled: (v) => has(v.email) },
  { key: "phone", label: "Phone", section: "identity", filled: (v) => has(v.phone) },
  { key: "links", label: "Links", section: "identity", filled: (v) => v.links.length > 0 },
  { key: "headline", label: "Headline", section: "identity", filled: (v) => has(v.headline) },
  { key: "target_titles", label: "Target titles", section: "experience", filled: (v) => v.target_titles.length > 0 },
  { key: "technical_skills", label: "Technical skills", section: "experience", filled: (v) => v.technical_skills.length > 0 },
  { key: "education", label: "Education", section: "background", filled: (v) => v.education.length > 0 },
  { key: "projects", label: "Projects", section: "background", filled: (v) => v.projects.length > 0 },
  { key: "preferred_locations", label: "Preferred locations", section: "preferences", filled: (v) => v.preferred_locations.length > 0 },
  { key: "work_arrangements", label: "Work arrangements", section: "preferences", filled: (v) => v.work_arrangements.length > 0 },
  { key: "employment_types", label: "Employment types", section: "preferences", filled: (v) => v.employment_types.length > 0 },
  { key: "open_to_relocation", label: "Relocation", section: "preferences", sensitive: true, filled: (v) => v.open_to_relocation !== "unset" },
  {
    key: "salary",
    label: "Salary expectation",
    section: "compensation",
    sensitive: true,
    filled: (v) => has(v.salary_expectation_min) || has(v.salary_expectation_max),
  },
  { key: "notice_period_days", label: "Notice period", section: "compensation", sensitive: true, filled: (v) => has(v.notice_period_days) },
  { key: "work_authorization", label: "Work authorization", section: "compensation", sensitive: true, filled: (v) => has(v.work_authorization) },
  { key: "requires_sponsorship", label: "Sponsorship", section: "compensation", sensitive: true, filled: (v) => v.requires_sponsorship !== "unset" },
];

export const SENSITIVE_FIELD_LABELS: Record<string, string> = {
  salary_expectation_min: "Salary expectation",
  salary_expectation_max: "Salary expectation",
  notice_period_days: "Notice period",
  work_authorization: "Work authorization",
  requires_sponsorship: "Sponsorship",
  open_to_relocation: "Relocation",
};

/** Backend field errors arrive as `{field: string[]}` (typed as strings in the client). */
export function flattenFieldErrors(fieldErrors: Record<string, unknown>): Array<{ path: string; message: string }> {
  const out: Array<{ path: string; message: string }> = [];
  for (const [path, value] of Object.entries(fieldErrors ?? {})) {
    const messages = Array.isArray(value) ? value.map(String) : [String(value)];
    for (const message of messages) out.push({ path, message: message.replace(/^Value error, /, "") });
  }
  return out;
}
