"use client";

import { ArrowUpRight, Briefcase, Globe, UserRound, type LucideIcon } from "lucide-react";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { formatDate } from "@/lib/formatting";
import { cn } from "@/lib/utils";

/** A citation as the research service writes it: what it is, where, and when it was read. */
export interface ResearchSource {
  id?: string;
  kind?: string;
  label?: string;
  url?: string;
  job_id?: number;
  retrieved_at?: string | null;
  posted_at?: string | null;
}

const KIND_ICON: Record<string, LucideIcon> = {
  job_listing: Briefcase,
  website: Globe,
  profile: UserRound,
};

export function asSource(value: unknown): ResearchSource | null {
  if (!value || typeof value !== "object") return null;
  return value as ResearchSource;
}

/**
 * A compact chip naming a fact's source and its date. The date shown is when the source was
 * read (or posted, for a listing with no read date); a source with neither says so.
 */
export function SourceCitation({ source, className }: { source: ResearchSource | null | undefined; className?: string }) {
  if (!source) {
    return <span className={cn("text-[11px] text-text-3 italic", className)}>source not recorded</span>;
  }
  const Icon = KIND_ICON[source.kind ?? ""] ?? Globe;
  const date = source.retrieved_at ?? source.posted_at ?? null;
  const dateLabel = source.retrieved_at ? "read" : source.posted_at ? "posted" : null;
  const label = source.label || source.kind?.replace(/_/g, " ") || "source";
  const body = (
    <>
      <Icon className="size-3 shrink-0" />
      <span className="max-w-[16rem] truncate">{label}</span>
      <span className="text-text-3">·</span>
      <span className="tabular text-text-3">{date ? `${dateLabel} ${formatDate(date)}` : "undated"}</span>
      {source.url ? <ArrowUpRight className="size-3 shrink-0 opacity-60" /> : null}
    </>
  );
  const chipClass = cn(
    "inline-flex max-w-full items-center gap-1 rounded-md bg-surface-2 px-1.5 py-0.5 text-[11px] text-text-2 ring-1 ring-inset ring-line transition-colors",
    source.url && "hover:bg-surface-3 hover:text-text-1",
    className,
  );
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        {source.url ? (
          <a href={source.url} target="_blank" rel="noopener noreferrer" className={chipClass}>
            {body}
          </a>
        ) : (
          <span className={chipClass} tabIndex={0}>
            {body}
          </span>
        )}
      </TooltipTrigger>
      <TooltipContent className="max-w-xs text-xs">
        <p className="font-medium">{label}</p>
        {source.url ? <p className="break-all opacity-80">{source.url}</p> : null}
        <p className="opacity-80">
          {source.retrieved_at ? `Read ${formatDate(source.retrieved_at)}` : "Read date not recorded"}
          {source.posted_at ? ` · posted ${formatDate(source.posted_at)}` : ""}
        </p>
      </TooltipContent>
    </Tooltip>
  );
}
