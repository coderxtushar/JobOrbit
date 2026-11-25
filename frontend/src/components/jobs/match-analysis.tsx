"use client";

import {
  AlertTriangle,
  Briefcase,
  CheckCircle2,
  CircleDashed,
  FileText,
  Gauge,
  Link2,
  MapPin,
  ShieldAlert,
  Sparkles,
  UserRound,
  XCircle,
  type LucideIcon,
} from "lucide-react";

import { EmptyState } from "@/components/shared/empty-state";
import { ScoreRing } from "@/components/shared/score-ring";
import { StateBadge, StatusBadge } from "@/components/shared/status-badge";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { Schemas } from "@/lib/api/client";
import { BAND, type Tone } from "@/lib/constants/states";
import { formatDateTime, humanize } from "@/lib/formatting";
import { cn } from "@/lib/utils";

type Match = Schemas["MatchRead"];
type Explanation = Schemas["JobExplanationRead"];
type Finding = Schemas["ExplanationFinding"];
type SkillFinding = Schemas["SkillFindingRead"];

interface CategoryScore {
  score: number | null;
  weight: number | null;
  contribution: number | null;
  detail: string;
  assessable: boolean;
}

/** category_scores is typed as an open dict by the API; read each entry defensively. */
function readCategories(match: Match): [string, CategoryScore][] {
  const raw = match.category_scores as unknown as Record<string, Record<string, unknown>> | null;
  if (!raw || typeof raw !== "object") return [];
  return Object.entries(raw).map(([key, value]) => {
    const num = (field: string) => (typeof value?.[field] === "number" ? (value[field] as number) : null);
    return [
      key,
      {
        score: num("score"),
        weight: num("weight"),
        contribution: num("contribution"),
        detail: typeof value?.detail === "string" ? value.detail : "",
        assessable: value?.assessable !== false,
      },
    ];
  });
}

const CONFIDENCE_TONE: Record<string, Tone> = { high: "success", medium: "warning", low: "danger" };

const SOURCE_META: Record<string, { label: string; icon: LucideIcon; className: string }> = {
  listing: { label: "From the listing", icon: FileText, className: "text-cyan" },
  profile: { label: "From your profile", icon: UserRound, className: "text-violet" },
  scoring: { label: "Scoring verdict", icon: Gauge, className: "text-text-2" },
};

const SECTION_ICON: Record<string, LucideIcon> = {
  strong_matches: CheckCircle2,
  missing_requirements: XCircle,
  experience_fit: Briefcase,
  location_fit: MapPin,
  evidence_quality: ShieldAlert,
  resume_relevance: Sparkles,
  downgrades: AlertTriangle,
};

/* ---------------- summary ---------------- */

function MatchSummary({ match }: { match: Match }) {
  const coverage = Math.round(Math.max(0, Math.min(1, match.evidence_coverage)) * 100);
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-4">
        <ScoreRing score={match.total_score} band={match.band} size={72} />
        <div className="min-w-0 flex-1 space-y-1.5">
          <div className="flex flex-wrap items-center gap-1.5">
            <StateBadge value={match.band} map={BAND} />
            <StatusBadge tone={CONFIDENCE_TONE[match.confidence] ?? "neutral"}>
              {humanize(match.confidence)} confidence
            </StatusBadge>
            {match.filtered_out ? <StatusBadge tone="danger">Held back by your filters</StatusBadge> : null}
          </div>
          <div>
            <div className="flex items-center justify-between text-[11.5px] text-text-3">
              <span>Evidence coverage</span>
              <span className="tabular text-text-2">{coverage}% of scoring weight assessable</span>
            </div>
            <div
              className="mt-1 h-1.5 overflow-hidden rounded-full bg-surface-3"
              role="meter"
              aria-label="Evidence coverage"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={coverage}
            >
              <div
                className="h-full rounded-full bg-gradient-to-r from-violet to-cyan transition-[width] duration-700"
                style={{ width: `${coverage}%` }}
              />
            </div>
          </div>
          <p className="text-[11px] text-text-3">
            Scored {formatDateTime(match.scored_at)} by the {humanize(match.scorer).toLowerCase()} scorer
          </p>
        </div>
      </div>

      {match.filtered_out && match.filter_reasons.length ? (
        <div className="rounded-lg border border-danger/25 bg-danger-soft p-3">
          <p className="flex items-center gap-1.5 text-xs font-semibold text-text-1">
            <ShieldAlert className="size-3.5 text-danger" aria-hidden /> Why this job is held back
          </p>
          <ul className="mt-1.5 space-y-1 text-xs leading-relaxed text-text-2">
            {match.filter_reasons.map((reason) => (
              <li key={reason} className="flex gap-1.5">
                <span aria-hidden className="mt-1.5 size-1 shrink-0 rounded-full bg-danger" />
                {reason}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {match.confidence_reasons.length || match.uncertain_requirements.length ? (
        <div className="rounded-lg border border-warning/25 bg-warning-soft p-3 text-xs leading-relaxed text-text-2">
          {match.confidence_reasons.length ? (
            <>
              <p className="font-semibold text-text-1">What lowers confidence</p>
              <ul className="mt-1 space-y-0.5">
                {match.confidence_reasons.map((reason) => (
                  <li key={reason}>· {reason}</li>
                ))}
              </ul>
            </>
          ) : null}
          {match.uncertain_requirements.length ? (
            <p className={cn(match.confidence_reasons.length && "mt-2")}>
              <span className="font-semibold text-text-1">Uncertain requirements: </span>
              {match.uncertain_requirements.join(", ")}
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function CategoryBreakdown({ match }: { match: Match }) {
  const categories = readCategories(match);
  if (!categories.length) return null;
  return (
    <div className="space-y-2.5">
      <p className="text-[11px] font-semibold uppercase tracking-wider text-text-3">Score breakdown</p>
      <ul className="space-y-2.5">
        {categories.map(([key, category]) => (
          <li key={key}>
            <div className="flex items-baseline justify-between gap-2 text-xs">
              <span className="font-medium text-text-1">{humanize(key)}</span>
              <span className="tabular text-text-3">
                {category.assessable && category.score !== null ? (
                  <>
                    <span className="text-text-1">{Math.round(category.score)}</span>/100
                  </>
                ) : (
                  "not assessable"
                )}
                {category.weight !== null ? ` · weight ${Math.round(category.weight * 100)}%` : ""}
              </span>
            </div>
            <div className="mt-1 h-1 overflow-hidden rounded-full bg-surface-3">
              {category.assessable && category.score !== null ? (
                <div
                  className={cn(
                    "h-full rounded-full",
                    category.score >= 75 ? "bg-success" : category.score >= 45 ? "bg-violet" : "bg-warning",
                  )}
                  style={{ width: `${Math.max(2, Math.min(100, category.score))}%` }}
                />
              ) : null}
            </div>
            {category.detail ? <p className="mt-1 text-[11.5px] leading-snug text-text-3">{category.detail}</p> : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

/* ---------------- skills ---------------- */

function SkillChip({ skill, tone }: { skill: SkillFinding; tone: "match" | "related" | "missing" | "profile" }) {
  const styles = {
    match: "border-success/30 bg-success-soft text-success",
    related: "border-violet/30 bg-violet-soft text-violet",
    missing: "border-danger/30 bg-danger-soft text-danger",
    profile: "border-line bg-surface-2 text-text-2",
  }[tone];
  const tip = [skill.note, skill.related_to ? `Related to your "${skill.related_to}"` : "", skill.quote ? `“${skill.quote}”` : ""]
    .filter(Boolean)
    .join("\n");
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          tabIndex={0}
          className={cn("inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11.5px] font-medium", styles)}
        >
          {skill.skill}
          {skill.evidence_class && tone !== "profile" ? (
            <span className="text-[10px] font-normal opacity-75">· {skill.evidence_class}</span>
          ) : null}
          {skill.related_to ? <Link2 className="size-3" aria-hidden /> : null}
        </span>
      </TooltipTrigger>
      {tip ? <TooltipContent className="max-w-72 whitespace-pre-line">{tip}</TooltipContent> : null}
    </Tooltip>
  );
}

function SkillGroup({
  title,
  hint,
  skills,
  tone,
  empty,
}: {
  title: string;
  hint: string;
  skills: SkillFinding[];
  tone: "match" | "related" | "missing" | "profile";
  empty: string;
}) {
  return (
    <div>
      <div className="flex items-baseline justify-between gap-2">
        <p className="text-xs font-semibold text-text-1">
          {title} <span className="tabular font-normal text-text-3">{skills.length}</span>
        </p>
        <p className="text-[11px] text-text-3">{hint}</p>
      </div>
      {skills.length ? (
        <div className="mt-1.5 flex flex-wrap gap-1">
          {skills.map((skill) => (
            <SkillChip key={`${skill.skill}-${skill.status}`} skill={skill} tone={tone} />
          ))}
        </div>
      ) : (
        <p className="mt-1 text-[11.5px] text-text-3">{empty}</p>
      )}
    </div>
  );
}

function SkillsAnalysis({ skills }: { skills: SkillFinding[] }) {
  const by = (status: string) => skills.filter((skill) => skill.status === status);
  const missing = by("not_in_profile");
  const order: Record<string, number> = { required: 0, preferred: 1, incidental: 2 };
  missing.sort((a, b) => (order[a.evidence_class] ?? 3) - (order[b.evidence_class] ?? 3));
  const profileOnly = by("not_in_listing");
  return (
    <div className="space-y-3.5">
      <SkillGroup
        title="Matched"
        hint="listing asks · you have"
        skills={by("in_profile")}
        tone="match"
        empty="None of the listing's skills are in your profile."
      />
      <SkillGroup
        title="Related"
        hint="close to something you have"
        skills={by("related_in_profile")}
        tone="related"
        empty="No partial matches."
      />
      <SkillGroup
        title="Missing"
        hint="listing asks · not in your profile"
        skills={missing}
        tone="missing"
        empty="Every skill this listing names is in your profile."
      />
      {profileOnly.length ? (
        <details className="group">
          <summary className="cursor-pointer list-none text-[11.5px] text-text-3 outline-none hover:text-text-1 focus-visible:text-text-1">
            <span className="underline decoration-dotted underline-offset-4">
              {profileOnly.length} of your skills this listing doesn&apos;t mention
            </span>
          </summary>
          <div className="mt-1.5 flex flex-wrap gap-1">
            {profileOnly.map((skill) => (
              <SkillChip key={skill.skill} skill={skill} tone="profile" />
            ))}
          </div>
        </details>
      ) : null}
    </div>
  );
}

/* ---------------- explanation sections ---------------- */

function FindingItem({ finding }: { finding: Finding }) {
  return (
    <li className="space-y-1">
      <p className="text-[12.5px] leading-relaxed text-text-1">{finding.statement}</p>
      {finding.quote ? (
        <blockquote className="border-l-2 border-cyan/50 pl-2 text-[11.5px] italic leading-relaxed text-text-3">
          “{finding.quote}”
        </blockquote>
      ) : null}
    </li>
  );
}

function FindingColumn({ source, findings }: { source: string; findings: Finding[] }) {
  const meta = SOURCE_META[source] ?? { label: humanize(source), icon: CircleDashed, className: "text-text-2" };
  const Icon = meta.icon;
  return (
    <div
      className={cn(
        "rounded-lg border p-2.5",
        source === "listing" && "border-cyan/20 bg-cyan-soft/40",
        source === "profile" && "border-violet/20 bg-violet-soft/40",
        source !== "listing" && source !== "profile" && "border-line bg-surface-2/60",
      )}
    >
      <p className={cn("mb-1.5 flex items-center gap-1 text-[10.5px] font-semibold uppercase tracking-wider", meta.className)}>
        <Icon className="size-3" aria-hidden /> {meta.label}
      </p>
      <ul className="space-y-2">
        {findings.map((finding, index) => (
          <FindingItem key={`${finding.statement}-${index}`} finding={finding} />
        ))}
      </ul>
    </div>
  );
}

function SectionBody({ section }: { section: Schemas["ExplanationSection"] }) {
  const findings = section.findings ?? [];
  if (!findings.length) {
    return <p className="text-xs text-text-3">{section.empty_note || "Nothing recorded."}</p>;
  }
  const listing = findings.filter((finding) => finding.source === "listing");
  const profile = findings.filter((finding) => finding.source === "profile");
  const other = findings.filter((finding) => finding.source !== "listing" && finding.source !== "profile");
  return (
    <div className="space-y-2">
      {listing.length || profile.length ? (
        <div className={cn("grid gap-2", listing.length && profile.length && "sm:grid-cols-2")}>
          {listing.length ? <FindingColumn source="listing" findings={listing} /> : null}
          {profile.length ? <FindingColumn source="profile" findings={profile} /> : null}
        </div>
      ) : null}
      {other.length ? <FindingColumn source="scoring" findings={other} /> : null}
    </div>
  );
}

function ExplanationSections({ explanation }: { explanation: Explanation }) {
  const sections = explanation.sections ?? [];
  if (!sections.length) return null;
  const defaults = sections
    .filter((section) => ["strong_matches", "missing_requirements", "downgrades"].includes(section.key))
    .filter((section) => (section.findings?.length ?? 0) > 0)
    .map((section) => section.key);
  return (
    <Accordion type="multiple" defaultValue={defaults} className="rounded-xl border border-line">
      {sections.map((section) => {
        const Icon = SECTION_ICON[section.key] ?? CircleDashed;
        const count = section.findings?.length ?? 0;
        return (
          <AccordionItem key={section.key} value={section.key} className="border-line px-3">
            <AccordionTrigger className="items-center py-3 hover:no-underline">
              <span className="flex items-center gap-2">
                <Icon
                  className={cn(
                    "size-4",
                    section.key === "strong_matches" && "text-success",
                    section.key === "missing_requirements" && "text-danger",
                    section.key === "downgrades" && (count ? "text-warning" : "text-text-3"),
                    !["strong_matches", "missing_requirements", "downgrades"].includes(section.key) && "text-text-2",
                  )}
                  aria-hidden
                />
                <span className="text-[13px] font-medium text-text-1">{section.title}</span>
                <span className="tabular text-[11px] text-text-3">{count}</span>
              </span>
            </AccordionTrigger>
            <AccordionContent className="pb-3">
              <SectionBody section={section} />
            </AccordionContent>
          </AccordionItem>
        );
      })}
    </Accordion>
  );
}

/* ---------------- container ---------------- */

export function MatchAnalysisSkeleton() {
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-4">
        <Skeleton className="size-[72px] rounded-full" />
        <div className="flex-1 space-y-2">
          <Skeleton className="h-5 w-40" />
          <Skeleton className="h-2 w-full" />
        </div>
      </div>
      <Skeleton className="h-24 w-full" />
      <Skeleton className="h-40 w-full" />
    </div>
  );
}

/**
 * The full match analysis for one job: the stored match (score, band, confidence,
 * breakdown, filter reasons) plus the explanation endpoint's evidence, keeping what the
 * listing says apart from what your profile says.
 */
export function MatchAnalysis({
  match,
  explanation,
  explanationLoading,
  explanationError,
  onScore,
  scoring,
}: {
  match: Match | null | undefined;
  explanation: Explanation | undefined;
  explanationLoading: boolean;
  explanationError: unknown;
  onScore?: () => void;
  scoring?: boolean;
}) {
  if (!match) {
    return (
      <EmptyState
        compact
        icon={Gauge}
        title="Not scored yet"
        description="This job has no match score, so there is nothing to explain. Scoring compares the listing with your profile."
        action={
          onScore ? (
            <Button size="sm" onClick={onScore} disabled={scoring}>
              <Gauge /> {scoring ? "Scoring…" : "Score this job"}
            </Button>
          ) : null
        }
      />
    );
  }

  return (
    <div className="space-y-5">
      <MatchSummary match={match} />
      <CategoryBreakdown match={match} />
      {explanationLoading ? (
        <MatchAnalysisSkeleton />
      ) : explanation ? (
        <>
          {explanation.skills?.length ? (
            <div className="space-y-2.5">
              <p className="text-[11px] font-semibold uppercase tracking-wider text-text-3">Skills</p>
              <SkillsAnalysis skills={explanation.skills} />
            </div>
          ) : null}
          <div className="space-y-2.5">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-text-3">Evidence</p>
            <ExplanationSections explanation={explanation} />
          </div>
        </>
      ) : explanationError ? (
        <p className="rounded-lg border border-line bg-surface-2 p-3 text-xs text-text-3">
          The detailed explanation could not be loaded: {(explanationError as Error).message}
        </p>
      ) : null}
    </div>
  );
}
