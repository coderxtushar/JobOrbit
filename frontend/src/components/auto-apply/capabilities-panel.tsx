"use client";

import { useQuery } from "@tanstack/react-query";
import { AnimatePresence, motion } from "motion/react";
import { ChevronDown, ExternalLink, ScrollText } from "lucide-react";
import { useState } from "react";

import { ErrorState } from "@/components/shared/query-state";
import { StatusBadge } from "@/components/shared/status-badge";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api/endpoints";
import { humanize } from "@/lib/formatting";
import { cn } from "@/lib/utils";

/**
 * Which platforms permit submission, and why, read from each adapter's own capability
 * report. Collapsed by default: it explains the run, it is not part of operating it.
 */
export function CapabilitiesPanel() {
  const [open, setOpen] = useState(false);
  const query = useQuery({ queryKey: ["autoapply", "capabilities"], queryFn: api.capabilities, staleTime: 5 * 60_000 });
  const supported = query.data?.supported_targets ?? [];

  return (
    <section className="orbit-card overflow-hidden">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-surface-2/50"
      >
        <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-cyan-soft text-cyan ring-1 ring-inset ring-cyan/20">
          <ScrollText className="size-4" />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-sm font-medium text-text-1">What each platform permits</span>
          <span className="block truncate text-xs text-text-3">
            {query.isPending
              ? "Reading each platform's capability report…"
              : query.isError
                ? "Could not be loaded"
                : supported.length
                  ? `Submission is permitted on ${supported.join(", ")}. Everything else is prepared for you to send.`
                  : "No platform currently permits automated submission. Applications are prepared for you to send."}
          </span>
        </span>
        <ChevronDown className={cn("size-4 shrink-0 text-text-3 transition-transform duration-200", open && "rotate-180")} />
      </button>
      <AnimatePresence initial={false}>
        {open ? (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.24, ease: [0.22, 1, 0.36, 1] }}
            className="overflow-hidden"
          >
            <div className="border-t border-line px-4 pb-4 pt-3">
              {query.isPending ? (
                <div className="space-y-2">
                  {Array.from({ length: 4 }).map((_, index) => (
                    <Skeleton key={index} className="h-9 w-full" />
                  ))}
                </div>
              ) : query.isError ? (
                <ErrorState error={query.error} onRetry={() => void query.refetch()} />
              ) : (
                <>
                  <p className="mb-3 text-xs leading-relaxed text-text-2">{query.data.note}</p>
                  <Accordion type="multiple" className="rounded-lg border border-line">
                    {query.data.platforms.map((platform) => (
                      <AccordionItem key={platform.key} value={platform.key} className="border-line px-3">
                        <AccordionTrigger className="py-2.5 hover:no-underline">
                          <span className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
                            <span className="text-sm font-medium text-text-1">{platform.display_name}</span>
                            <StatusBadge tone={platform.submission_supported ? "success" : "neutral"}>
                              {platform.submission_supported ? "Submission permitted" : "No submission"}
                            </StatusBadge>
                            <span className="text-[11px] text-text-3">
                              credential: {humanize(platform.credential_owner) || "—"}
                            </span>
                          </span>
                        </AccordionTrigger>
                        <AccordionContent className="space-y-2 pb-3 text-xs leading-relaxed text-text-2">
                          <p>{platform.reason}</p>
                          <div className="flex flex-wrap gap-1.5">
                            <Flag on={platform.documented_api} label="Documented API" />
                            <Flag on={platform.browser_submission_permitted} label="Browser submission permitted" />
                            <Flag on={!platform.manual_completion_required} label="No manual completion needed" />
                          </div>
                          {platform.evidence_quote ? (
                            <blockquote className="border-l-2 border-line-strong pl-3 italic text-text-3">
                              “{platform.evidence_quote}”
                            </blockquote>
                          ) : null}
                          {platform.evidence_url ? (
                            <a
                              href={platform.evidence_url}
                              target="_blank"
                              rel="noreferrer noopener"
                              className="inline-flex items-center gap-1 text-violet hover:underline"
                            >
                              Source <ExternalLink className="size-3" />
                            </a>
                          ) : null}
                        </AccordionContent>
                      </AccordionItem>
                    ))}
                  </Accordion>
                </>
              )}
            </div>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </section>
  );
}

function Flag({ on, label }: { on: boolean; label: string }) {
  return (
    <StatusBadge tone={on ? "success" : "neutral"} dot>
      {on ? label : `Not: ${label.toLowerCase()}`}
    </StatusBadge>
  );
}
