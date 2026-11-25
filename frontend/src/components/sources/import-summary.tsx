"use client";

import { ChevronRight } from "lucide-react";

import { StateBadge } from "@/components/shared/status-badge";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import type { Schemas } from "@/lib/api/client";
import { formatNumber } from "@/lib/formatting";

import { IMPORT_STATUS } from "./import-status";

/** The result of one import or discovery run for one source. */
export function ImportSummaryCard({
  summary,
  displayName,
}: {
  summary: Schemas["ImportSummary"];
  displayName?: string;
}) {
  const errors = summary.errors ?? [];
  const warnings = summary.warnings ?? [];
  const counts = [
    { label: "new", value: summary.jobs_created },
    { label: "enriched", value: summary.jobs_updated },
    { label: "duplicate", value: summary.duplicates_detected },
    { label: "invalid", value: summary.records_invalid },
    { label: "received", value: summary.records_received },
  ];
  return (
    <div className="rounded-lg border border-line bg-surface-2/40 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-medium text-text-1">{displayName ?? summary.source}</p>
        <StateBadge value={summary.status} map={IMPORT_STATUS} />
      </div>
      <p className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-xs text-text-3">
        {counts.map((count) => (
          <span key={count.label}>
            <span className={count.value ? "font-medium text-text-1 tabular" : "tabular"}>{formatNumber(count.value)}</span>{" "}
            {count.label}
          </span>
        ))}
      </p>
      {summary.message && (summary.status !== "success" || !errors.length) ? (
        <p className="mt-1.5 text-xs leading-relaxed text-text-2">{summary.message}</p>
      ) : null}
      {[
        { title: "error", items: errors.filter((error) => error !== summary.message) },
        { title: "note", items: warnings },
      ].map((group) =>
        group.items.length ? (
          <Collapsible key={group.title} className="mt-2">
            <CollapsibleTrigger className="group flex items-center gap-1 text-xs text-text-3 hover:text-text-1">
              <ChevronRight className="size-3.5 transition-transform group-data-[state=open]:rotate-90" />
              {group.items.length} {group.title}
              {group.items.length === 1 ? "" : "s"} from this run
            </CollapsibleTrigger>
            <CollapsibleContent>
              <ul className="mt-1.5 space-y-1 pl-5 text-xs text-text-2">
                {group.items.map((item, index) => (
                  <li key={index} className="list-disc">
                    {item}
                  </li>
                ))}
              </ul>
            </CollapsibleContent>
          </Collapsible>
        ) : null,
      )}
    </div>
  );
}
