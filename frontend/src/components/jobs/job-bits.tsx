"use client";

import type { LucideIcon } from "lucide-react";

import { StatusBadge } from "@/components/shared/status-badge";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

import { sourceLabel, type Verdict } from "./job-utils";

/** A small metadata item: icon + text, used in card and detail meta rows. */
export function Meta({
  icon: Icon,
  children,
  className,
  title,
}: {
  icon: LucideIcon;
  children: React.ReactNode;
  className?: string;
  title?: string;
}) {
  return (
    <span className={cn("inline-flex min-w-0 items-center gap-1 text-text-2", className)} title={title}>
      <Icon className="size-3.5 shrink-0 text-text-3" aria-hidden />
      <span className="truncate">{children}</span>
    </span>
  );
}

/** A derived verdict as a badge, with the listing evidence behind it in a tooltip. */
export function VerdictBadge({ verdict, prefix }: { verdict: Verdict; prefix?: string }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span tabIndex={0} className="rounded-full focus-visible:outline-2">
          <StatusBadge tone={verdict.tone}>
            {prefix ? <span className="sr-only">{prefix}: </span> : null}
            {verdict.label}
          </StatusBadge>
        </span>
      </TooltipTrigger>
      <TooltipContent className="max-w-64">{verdict.detail}</TooltipContent>
    </Tooltip>
  );
}

export function SourceChips({ sources, max = 3 }: { sources: string[]; max?: number }) {
  if (!sources.length) return <span className="text-[11.5px] text-text-3">No source recorded</span>;
  const shown = sources.slice(0, max);
  const rest = sources.length - shown.length;
  return (
    <span className="inline-flex flex-wrap items-center gap-1">
      {shown.map((source) => (
        <span
          key={source}
          className="rounded-md border border-line bg-surface-2 px-1.5 py-px text-[11px] font-medium text-text-2"
        >
          {sourceLabel(source)}
        </span>
      ))}
      {rest > 0 ? (
        <span className="text-[11px] text-text-3" title={sources.slice(max).map(sourceLabel).join(", ")}>
          +{rest}
        </span>
      ) : null}
    </span>
  );
}

/** Company monogram. Deterministic, no external logos (none are in the data). */
export function CompanyMark({ company, size = "md" }: { company: string; size?: "md" | "lg" }) {
  const letter = company.trim().charAt(0).toUpperCase() || "?";
  return (
    <span
      aria-hidden
      className={cn(
        "grid shrink-0 place-items-center rounded-lg bg-gradient-to-br from-violet-soft to-cyan-soft font-heading font-semibold text-text-1 ring-1 ring-inset ring-line-strong",
        size === "lg" ? "size-11 text-base" : "size-9 text-sm",
      )}
    >
      {letter}
    </span>
  );
}
