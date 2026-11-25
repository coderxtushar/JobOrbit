"use client";

import {
  BookOpen,
  Boxes,
  Briefcase,
  Code2,
  FolderGit2,
  Globe,
  Lightbulb,
  ListChecks,
  Quote,
  Target,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { motion, useReducedMotion } from "motion/react";

import { StatusBadge } from "@/components/shared/status-badge";
import { Surface } from "@/components/shared/surface";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { formatDate } from "@/lib/formatting";
import { cn } from "@/lib/utils";

import type { CitedQuote, CompanyData, JobContext, SkillFact, StatedBlock } from "./research-types";
import { SourceCitation, type ResearchSource } from "./source-citation";

const NOT_STATED = "not stated in the available sources";

export function NotStated({ children = "Not stated", className }: { children?: React.ReactNode; className?: string }) {
  return <span className={cn("text-sm text-text-3 italic", className)}>{children}</span>;
}

/** A card section with an icon heading, used for every block of the profile. */
export function ResearchSection({
  icon: Icon,
  title,
  description,
  children,
  className,
  index = 0,
  aside,
}: {
  icon: LucideIcon;
  title: string;
  description?: string;
  children: React.ReactNode;
  className?: string;
  index?: number;
  aside?: React.ReactNode;
}) {
  const reduced = useReducedMotion();
  return (
    <motion.section
      initial={reduced ? false : { opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.32, delay: Math.min(index, 8) * 0.04, ease: [0.22, 1, 0.36, 1] }}
      className={className}
    >
      <Surface className="h-full p-4 sm:p-5">
        <header className="mb-3 flex items-start justify-between gap-3">
          <div className="flex items-start gap-2.5">
            <span className="mt-0.5 grid size-7 shrink-0 place-items-center rounded-lg bg-violet-soft text-violet ring-1 ring-inset ring-violet/20">
              <Icon className="size-3.5" />
            </span>
            <div>
              <h3 className="font-heading text-sm font-semibold text-text-1">{title}</h3>
              {description ? <p className="mt-0.5 text-xs text-text-3">{description}</p> : null}
            </div>
          </div>
          {aside}
        </header>
        {children}
      </Surface>
    </motion.section>
  );
}

function QuoteBlock({ quote, source, where }: { quote: string; source?: ResearchSource | null; where?: string }) {
  return (
    <figure className="space-y-2 rounded-lg border border-line bg-surface-2/50 p-3">
      <blockquote className="flex gap-2 text-[13px] leading-relaxed text-text-2">
        <Quote className="mt-0.5 size-3.5 shrink-0 text-violet/70" aria-hidden />
        <span>{quote}</span>
      </blockquote>
      <figcaption className="flex flex-wrap items-center gap-1.5 pl-5.5 text-[11px] text-text-3">
        {where ? <span>{where} ·</span> : null}
        <SourceCitation source={source} />
      </figcaption>
    </figure>
  );
}

function Stated({ block }: { block: StatedBlock | undefined }) {
  if (!block?.stated || !block.facts?.length) {
    return <NotStated>{block?.message || NOT_STATED}</NotStated>;
  }
  return (
    <ul className="space-y-2">
      {block.facts.map((fact, index) => (
        <li key={`${fact.statement}-${index}`} className="space-y-1.5">
          <StatusBadge tone="cyan" dot={false}>
            {fact.statement}
          </StatusBadge>
          <QuoteBlock quote={fact.quote} source={fact.source} />
        </li>
      ))}
    </ul>
  );
}

/** The cited company profile: only what a held listing, your profile or a fetched page says. */
export function CompanyProfileSections({
  data,
  sources,
}: {
  data: CompanyData;
  sources: Map<string, ResearchSource>;
}) {
  const about: CitedQuote[] = data.about ?? [];
  const technologies = data.technologies ?? [];
  const focus = data.engineering_focus ?? [];
  const listings = data.listings ?? [];
  const website = data.website ?? null;

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <ResearchSection
        index={0}
        icon={BookOpen}
        title="How the company describes itself"
        description="Quoted from its listings, never paraphrased into a claim."
        className="lg:col-span-2"
      >
        {about.length ? (
          <div className="grid gap-2.5 md:grid-cols-2">
            {about.slice(0, 4).map((item, index) => (
              <QuoteBlock key={index} quote={item.quote} where={item.where} source={item.source} />
            ))}
          </div>
        ) : (
          <NotStated>{NOT_STATED}</NotStated>
        )}
      </ResearchSection>

      <ResearchSection index={1} icon={Briefcase} title="Business model">
        <Stated block={data.business_model} />
      </ResearchSection>

      <ResearchSection index={2} icon={Boxes} title="Products">
        <Stated block={data.products} />
      </ResearchSection>

      <ResearchSection
        index={3}
        icon={Code2}
        title="Technologies in its listings"
        description="Skills counted across the listings JobOrbit holds. Hover for the sources."
      >
        {technologies.length ? (
          <ul className="flex flex-wrap gap-1.5">
            {technologies.slice(0, 40).map((tech) => {
              const cited = (tech.source_ids ?? []).map((id) => sources.get(id)).filter(Boolean) as ResearchSource[];
              return (
                <li key={tech.skill}>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <span
                        tabIndex={0}
                        className="inline-flex items-center gap-1.5 rounded-md bg-surface-2 px-2 py-0.5 text-xs text-text-1 ring-1 ring-inset ring-line transition-colors hover:bg-surface-3"
                      >
                        {tech.skill}
                        <span className="tabular text-[10.5px] text-text-3">×{tech.listing_count}</span>
                      </span>
                    </TooltipTrigger>
                    <TooltipContent className="max-w-xs text-xs">
                      <p className="font-medium">
                        In {tech.listing_count} listing{tech.listing_count === 1 ? "" : "s"}
                      </p>
                      {cited.slice(0, 4).map((source) => (
                        <p key={source.id} className="opacity-80">
                          {source.label} · read {formatDate(source.retrieved_at)}
                        </p>
                      ))}
                    </TooltipContent>
                  </Tooltip>
                </li>
              );
            })}
          </ul>
        ) : (
          <NotStated>No skills are listed in its listings.</NotStated>
        )}
      </ResearchSection>

      <ResearchSection index={4} icon={Globe} title="Website" description="Fetched only when you ask and the server allows it.">
        <WebsiteBlock website={website} />
      </ResearchSection>

      <ResearchSection
        index={5}
        icon={Lightbulb}
        title="Engineering focus"
        description="Themes found in listing text, with the lines that triggered them."
        className="lg:col-span-2"
      >
        {focus.length ? (
          <div className="grid gap-3 md:grid-cols-2">
            {focus.slice(0, 6).map((theme) => (
              <div key={theme.theme} className="space-y-2 rounded-lg border border-line p-3">
                <div className="flex flex-wrap items-center gap-1.5">
                  <p className="text-sm font-medium text-text-1">{theme.theme}</p>
                  {(theme.phrases ?? []).slice(0, 5).map((phrase) => (
                    <span key={phrase} className="rounded bg-violet-soft px-1.5 py-px text-[10.5px] text-violet">
                      {phrase}
                    </span>
                  ))}
                </div>
                {(theme.evidence ?? []).slice(0, 2).map((evidence, index) => (
                  <QuoteBlock key={index} quote={evidence.quote} source={evidence.source} />
                ))}
              </div>
            ))}
          </div>
        ) : (
          <NotStated>{NOT_STATED}</NotStated>
        )}
      </ResearchSection>

      <ResearchSection
        index={6}
        icon={ListChecks}
        title="Listings this is built from"
        description={`${listings.length} listing${listings.length === 1 ? "" : "s"} held by JobOrbit.`}
        className="lg:col-span-2"
      >
        {listings.length ? (
          <ul className="divide-y divide-line">
            {listings.slice(0, 12).map((listing) => (
              <li key={listing.job_id} className="flex flex-col gap-1 py-2 sm:flex-row sm:items-center sm:justify-between">
                <div className="min-w-0">
                  <Link
                    href={`/company-research?job=${listing.job_id}`}
                    className="truncate text-sm text-text-1 hover:text-violet focus-visible:text-violet"
                  >
                    {listing.title}
                  </Link>
                  <p className="text-xs text-text-3">{listing.location || "Location not stated"}</p>
                </div>
                <SourceCitation source={listing.source} />
              </li>
            ))}
            {listings.length > 12 ? (
              <li className="pt-2 text-xs text-text-3">and {listings.length - 12} more listings.</li>
            ) : null}
          </ul>
        ) : (
          <NotStated>No listings for this company are held.</NotStated>
        )}
      </ResearchSection>
    </div>
  );
}

function WebsiteBlock({ website }: { website: CompanyData["website"] }) {
  if (!website || !website.url) return <NotStated>No website is known. JobOrbit never guesses one from the name.</NotStated>;
  const href = website.final_url || website.url;
  const source: ResearchSource = {
    id: "website",
    kind: "website",
    label: "company website",
    url: href,
    retrieved_at: website.fetched_at ?? null,
  };
  return (
    <div className="space-y-2 text-sm">
      <a href={href} target="_blank" rel="noopener noreferrer" className="break-all text-violet hover:underline">
        {href}
      </a>
      {website.error ? (
        <p className="rounded-md bg-warning-soft px-2.5 py-1.5 text-xs text-text-2 ring-1 ring-inset ring-warning/25">
          The last fetch failed: {website.error}
          {website.fetched_at ? ` (${formatDate(website.fetched_at)})` : ""}
        </p>
      ) : website.note ? (
        <p className="text-xs text-text-3">{website.note}</p>
      ) : null}
      {website.title || website.description ? (
        <div className="space-y-1 rounded-lg border border-line bg-surface-2/50 p-3">
          {website.title ? <p className="font-medium text-text-1">{website.title}</p> : null}
          <p className="text-xs leading-relaxed text-text-2">{website.description || <NotStated>No meta description.</NotStated>}</p>
          <SourceCitation source={source} />
        </div>
      ) : null}
    </div>
  );
}

function SkillList({ facts, tone }: { facts: SkillFact[]; tone: "violet" | "neutral" }) {
  if (!facts.length) return <NotStated>None stated</NotStated>;
  return (
    <ul className="flex flex-wrap gap-1.5">
      {facts.map((fact) => (
        <li key={fact.skill}>
          <Tooltip>
            <TooltipTrigger asChild>
              <span
                tabIndex={0}
                className={cn(
                  "inline-flex rounded-md px-2 py-0.5 text-xs ring-1 ring-inset",
                  tone === "violet" ? "bg-violet-soft text-violet ring-violet/25" : "bg-surface-2 text-text-1 ring-line",
                )}
              >
                {fact.skill}
              </span>
            </TooltipTrigger>
            <TooltipContent className="max-w-xs text-xs">
              <p>{fact.quote ? `“${fact.quote}”` : `From ${fact.where || "the listing"}`}</p>
              {fact.source?.label ? <p className="opacity-80">{fact.source.label}</p> : null}
            </TooltipContent>
          </Tooltip>
        </li>
      ))}
    </ul>
  );
}

/** This job's requirements, your matching projects and topics, each with what it came from. */
export function JobContextSection({ context }: { context: JobContext }) {
  const requirements = context.requirements ?? {};
  const projects = context.relevant_projects ?? [];
  const topics = context.interview_topics ?? [];
  return (
    <ResearchSection
      icon={Target}
      title={`For this job: ${context.title ?? "selected listing"}`}
      description="The listing's requirements next to what your profile already records."
      aside={<SourceCitation source={context.source} />}
      className="lg:col-span-2"
    >
      <div className="grid gap-5 lg:grid-cols-3">
        <div className="space-y-4">
          <div className="space-y-1.5">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-text-3">Required skills</p>
            <SkillList facts={requirements.required_skills ?? []} tone="violet" />
          </div>
          <div className="space-y-1.5">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-text-3">Preferred skills</p>
            <SkillList facts={requirements.preferred_skills ?? []} tone="neutral" />
          </div>
          <div className="space-y-1.5">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-text-3">Experience</p>
            {requirements.experience?.quote ? (
              <p className="text-sm text-text-1">“{requirements.experience.quote}”</p>
            ) : (
              <NotStated />
            )}
          </div>
          <div className="space-y-1.5">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-text-3">Education</p>
            {requirements.education?.length ? (
              <ul className="space-y-1 text-sm text-text-1">
                {requirements.education.map((item, index) => (
                  <li key={index}>“{item.quote}”</li>
                ))}
              </ul>
            ) : (
              <NotStated />
            )}
          </div>
        </div>

        <div className="space-y-2">
          <p className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-text-3">
            <FolderGit2 className="size-3" /> Your relevant projects
          </p>
          {projects.length ? (
            <ul className="space-y-2">
              {projects.map((project) => (
                <li key={project.name} className="space-y-1.5 rounded-lg border border-line p-3">
                  <p className="text-sm font-medium text-text-1">{project.name}</p>
                  {project.overlap?.length ? (
                    <p className="text-xs text-text-2">
                      Overlaps on <span className="text-cyan">{project.overlap.join(", ")}</span>
                    </p>
                  ) : null}
                  {project.quote ? <p className="line-clamp-3 text-xs text-text-3">{project.quote}</p> : null}
                  <SourceCitation source={project.source} />
                </li>
              ))}
            </ul>
          ) : (
            <NotStated>None of your recorded projects share a skill with this listing.</NotStated>
          )}
        </div>

        <div className="space-y-2">
          <p className="flex items-center justify-between gap-2 text-[11px] font-semibold uppercase tracking-wider text-text-3">
            <span>Likely interview topics</span>
            <StatusBadge tone="violet" dot={false} className="normal-case tracking-normal">
              Generated · rule-based
            </StatusBadge>
          </p>
          {topics.length ? (
            <ul className="space-y-2">
              {topics.map((topic, index) => (
                <li key={index} className="rounded-lg border border-line p-2.5">
                  <p className="text-[13px] text-text-1">{topic.topic}</p>
                  <p className="mt-0.5 text-[11px] text-text-3">Derived from {topic.derived_from}</p>
                </li>
              ))}
            </ul>
          ) : (
            <NotStated>No topics could be derived from this listing.</NotStated>
          )}
        </div>
      </div>
    </ResearchSection>
  );
}
