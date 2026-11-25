"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Inbox, Link2, Loader2, X } from "lucide-react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useId, useState } from "react";
import { toast } from "sonner";

import { EmptyState } from "@/components/shared/empty-state";
import { ErrorState, errorMessage } from "@/components/shared/query-state";
import { StateBadge, StatusBadge } from "@/components/shared/status-badge";
import { Surface } from "@/components/shared/surface";
import { Button } from "@/components/ui/button";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api/endpoints";
import type { Schemas } from "@/lib/api/client";
import { APPLICATION_STATUS } from "@/lib/constants/states";
import { formatDateTime, formatRelative } from "@/lib/formatting";
import { cn } from "@/lib/utils";

import { categoryLabel, fieldLabel, percent } from "./labels";

type Message = Schemas["EmailMessageRead"];

interface Candidate {
  application_id: number;
  score: number;
  job_title: string;
  company: string;
  status: string;
  signals: string[];
}

const FACT_LABELS: [string, string][] = [
  ["employer", "Employer"],
  ["job_title", "Job title"],
  ["application_reference", "Reference"],
  ["interview_date", "Interview date"],
  ["interview_time", "Interview time"],
  ["interview_timezone", "Timezone"],
  ["deadline", "Deadline"],
];

function candidatesOf(message: Message): Candidate[] {
  return (message.match_candidates as unknown as Candidate[]).filter(
    (candidate) => typeof candidate?.application_id === "number",
  );
}

/** Emails the matcher could not attribute to one application with confidence. */
export function ReviewInbox() {
  const messages = useQuery({
    queryKey: ["email", "messages", "needs_review"],
    queryFn: () => api.emailMessages({ match_state: "needs_review", limit: 100 }),
  });
  const reduced = useReducedMotion();

  if (messages.isLoading) {
    return (
      <div className="space-y-3">
        {Array.from({ length: 2 }).map((_, index) => (
          <Skeleton key={index} className="h-56 w-full rounded-xl" />
        ))}
      </div>
    );
  }
  if (messages.isError) return <ErrorState error={messages.error} onRetry={() => messages.refetch()} />;

  const items = messages.data?.items ?? [];
  if (!items.length) {
    return (
      <EmptyState
        icon={Inbox}
        title="No email needs your pick"
        description="When an email could belong to more than one application, it waits here with the likely candidates and why each was proposed. Nothing is linked by guessing."
      />
    );
  }

  return (
    <ul className="space-y-3">
      <AnimatePresence initial={false}>
        {items.map((message) => (
          <motion.li
            key={message.id}
            layout={!reduced}
            initial={reduced ? false : { opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={reduced ? { opacity: 0 } : { opacity: 0, x: 12 }}
            transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
          >
            <ReviewCard message={message} />
          </motion.li>
        ))}
      </AnimatePresence>
    </ul>
  );
}

function ReviewCard({ message }: { message: Message }) {
  const queryClient = useQueryClient();
  const groupId = useId();
  const candidates = candidatesOf(message);
  const [picked, setPicked] = useState<string>("");
  const category = categoryLabel(message.category);
  const extracted = (message.extracted ?? {}) as Record<string, unknown>;
  const facts = FACT_LABELS.filter(([key]) => typeof extracted[key] === "string" && extracted[key]);

  const refresh = () => queryClient.invalidateQueries({ queryKey: ["email"] });

  const link = useMutation({
    mutationFn: (applicationId: number) => api.linkEmail(message.id, { application_id: applicationId }),
    onSuccess: (result) => {
      toast.success("Email linked", {
        description: result.suggestion
          ? `Suggested ${fieldLabel(result.suggestion.field).toLowerCase()} → ${result.suggestion.suggested_value}. Review it under Suggestions; nothing is applied yet.`
          : "No status change follows from this kind of email.",
      });
      void refresh();
    },
    onError: (failure) => toast.error("Could not link the email", { description: errorMessage(failure) }),
  });

  const dismiss = useMutation({
    mutationFn: () => api.dismissEmail(message.id),
    onSuccess: () => {
      toast.success("Marked as not about any application");
      void refresh();
    },
    onError: (failure) => toast.error("Could not dismiss the email", { description: errorMessage(failure) }),
  });

  const busy = link.isPending || dismiss.isPending;

  return (
    <Surface className="overflow-hidden p-0">
      <div className="space-y-3 p-4 sm:p-5">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0 space-y-1">
            <p className="font-medium text-text-1">{message.subject || "(no subject)"}</p>
            <p className="truncate text-xs text-text-3">
              {message.sender || "Unknown sender"}
              {message.received_at ? (
                <span title={formatDateTime(message.received_at)}> · {formatRelative(message.received_at)}</span>
              ) : null}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-1.5">
            <StatusBadge tone={category.tone} dot={false}>
              {category.label}
            </StatusBadge>
            <span className="text-[11px] text-text-3 tabular">{percent(message.confidence)}</span>
          </div>
        </div>
        {message.snippet ? (
          <p className="line-clamp-3 rounded-lg bg-surface-2/70 px-3 py-2 text-xs leading-relaxed text-text-2 ring-1 ring-inset ring-line">
            {message.snippet}
          </p>
        ) : null}
        {facts.length ? (
          <dl className="flex flex-wrap gap-x-5 gap-y-1 text-xs">
            {facts.map(([key, label]) => (
              <div key={key} className="flex gap-1.5">
                <dt className="text-text-3">{label}</dt>
                <dd className="text-text-1">{String(extracted[key])}</dd>
              </div>
            ))}
          </dl>
        ) : null}
      </div>

      <div className="space-y-3 border-t border-line bg-surface-2/35 p-4 sm:p-5">
        <p id={`${groupId}-label`} className="text-xs font-medium text-text-2">
          Which application is this about?
        </p>
        {candidates.length ? (
          <RadioGroup value={picked} onValueChange={setPicked} aria-labelledby={`${groupId}-label`} className="gap-2">
            {candidates.map((candidate) => {
              const value = String(candidate.application_id);
              const id = `${groupId}-${value}`;
              return (
                <label
                  key={value}
                  htmlFor={id}
                  className={cn(
                    "flex cursor-pointer items-start gap-3 rounded-lg border border-line bg-surface-1 p-3 transition-colors hover:border-line-strong",
                    picked === value && "border-violet/50 bg-violet-soft",
                  )}
                >
                  <RadioGroupItem id={id} value={value} className="mt-0.5" />
                  <span className="min-w-0 flex-1 space-y-1">
                    <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                      <span className="text-sm font-medium text-text-1">{candidate.job_title || "Untitled role"}</span>
                      <span className="text-xs text-text-2">{candidate.company || "Company not recorded"}</span>
                      <StateBadge value={candidate.status} map={APPLICATION_STATUS} />
                    </span>
                    <span className="flex flex-wrap items-center gap-1 text-[11px] text-text-3">
                      <span className="tabular">#{candidate.application_id} · match score {percent(candidate.score)}</span>
                      {candidate.signals.map((signal) => (
                        <span key={signal} className="rounded bg-surface-3 px-1.5 py-0.5 text-text-2">
                          {signal}
                        </span>
                      ))}
                    </span>
                  </span>
                </label>
              );
            })}
          </RadioGroup>
        ) : (
          <p className="text-xs text-text-3">The matcher proposed no candidates. Dismiss it if it is not about an application.</p>
        )}
        <div className="flex flex-wrap justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={() => dismiss.mutate()} disabled={busy}>
            {dismiss.isPending ? <Loader2 className="animate-spin" /> : <X />}
            Not about any application
          </Button>
          <Button size="sm" onClick={() => link.mutate(Number(picked))} disabled={busy || !picked}>
            {link.isPending ? <Loader2 className="animate-spin" /> : <Link2 />}
            Link to selected
          </Button>
        </div>
      </div>
    </Surface>
  );
}
