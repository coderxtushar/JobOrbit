/**
 * Shapes of the research payloads the backend types as free-form dicts
 * (`CompanyResearchRead.data`, `InterviewPrepRead.content`...). Written from
 * app/services/company_research.py and app/services/interview_prep.py. Every field is
 * optional on purpose: a missing value renders as "not stated", never as a guess.
 */
import { ApiError } from "@/lib/api/client";

import type { ResearchSource } from "./source-citation";

export interface CitedQuote {
  quote: string;
  where?: string;
  source?: ResearchSource | null;
}

export interface StatedFact {
  statement: string;
  quote: string;
  source?: ResearchSource | null;
}

export interface StatedBlock {
  stated?: boolean;
  facts?: StatedFact[];
  message?: string;
}

export interface Technology {
  skill: string;
  listing_count: number;
  source_ids?: string[];
}

export interface FocusTheme {
  theme: string;
  phrases?: string[];
  evidence?: { quote: string; source?: ResearchSource | null }[];
}

export interface Listing {
  job_id: number;
  title: string;
  location?: string;
  url?: string;
  posted_at?: string | null;
  retrieved_at?: string | null;
  source?: ResearchSource | null;
}

export interface WebsiteSummary {
  url?: string;
  final_url?: string;
  fetched_at?: string | null;
  title?: string;
  description?: string;
  error?: string;
  note?: string;
}

export interface CompanyData {
  display_name?: string;
  listing_count?: number;
  first_seen?: string | null;
  last_seen?: string | null;
  listings?: Listing[];
  about?: CitedQuote[];
  business_model?: StatedBlock;
  products?: StatedBlock;
  technologies?: Technology[];
  engineering_focus?: FocusTheme[];
  website?: WebsiteSummary | null;
  notes?: string[];
}

export interface SkillFact {
  skill: string;
  level?: string;
  quote?: string;
  where?: string;
  source?: ResearchSource | null;
}

export interface JobContext {
  job_id?: number;
  title?: string;
  source?: ResearchSource | null;
  requirements?: {
    required_skills?: SkillFact[];
    preferred_skills?: SkillFact[];
    experience?: { quote: string; source?: ResearchSource | null } | null;
    education?: { quote: string; source?: ResearchSource | null }[];
  };
  relevant_projects?: { name: string; overlap?: string[]; quote?: string; source?: ResearchSource | null }[];
  interview_topics?: { topic: string; derived_from: string; source?: ResearchSource | null }[];
  company_profile_refreshed_at?: string | null;
}

// ---------------------------------------------------------------- interview prep

export interface PrepItem {
  id: string;
  kind: string;
  question: string;
  derived_from: string;
  skill?: string;
  level?: string;
  project?: string;
  source?: ResearchSource | null;
  times_practised?: number;
}

export interface PrepContent {
  application_id?: number;
  job?: {
    id?: number;
    title?: string;
    company?: string;
    family?: string;
    required_skills?: string[];
    preferred_skills?: string[];
  };
  generated_by?: string;
  generated_at?: string;
  sections?: Record<string, PrepItem[]>;
  notes?: string[];
}

export interface PracticeFeedback {
  points?: string[];
  checks?: {
    word_count?: number;
    star?: Record<string, boolean>;
    skills_mentioned?: string[];
    has_example?: boolean;
    has_numbers?: boolean;
  };
  disclaimer?: string;
}

export interface PracticeEntry {
  question_id: string;
  kind: string;
  question: string;
  answer: string;
  feedback: PracticeFeedback;
  answered_at: string;
}

/** Sections in the order the backend builds them; practice draws from the first four. */
export const PREP_SECTIONS: { key: string; label: string; hint: string; practisable: boolean }[] = [
  { key: "technical", label: "Technical", hint: "From the listing's skills and responsibilities", practisable: true },
  { key: "resume", label: "Your resume", hint: "From what your profile and resume already state", practisable: true },
  { key: "projects", label: "Your projects", hint: "From the projects you recorded", practisable: true },
  { key: "behavioural", label: "Behavioural", hint: "Standard questions, tailored to the job family", practisable: true },
  { key: "coding", label: "Coding topics", hint: "Topics to practise, inferred from the title and skills", practisable: false },
  { key: "company", label: "Company topics", hint: "From the cited company profile", practisable: false },
  { key: "skill_gaps", label: "Skill gaps", hint: "Topics to prepare, not claims to make", practisable: false },
];

export const PRACTICE_KINDS = PREP_SECTIONS.filter((section) => section.practisable);

export function sectionLabel(kind: string): string {
  return PREP_SECTIONS.find((section) => section.key === kind)?.label ?? kind.replace(/_/g, " ");
}

export function isNotGenerated(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404 && error.code === "interview_prep_not_generated";
}

/** Backend field errors arrive as `{field: string[]}` even though the client types them as strings. */
export function fieldErrorText(value: unknown): string {
  if (Array.isArray(value)) return value.map(String).join(" ");
  return value ? String(value) : "";
}

export function sourceMap(sources: unknown[] | undefined): Map<string, ResearchSource> {
  const map = new Map<string, ResearchSource>();
  for (const raw of sources ?? []) {
    const source = raw as ResearchSource;
    if (source?.id) map.set(source.id, source);
  }
  return map;
}
