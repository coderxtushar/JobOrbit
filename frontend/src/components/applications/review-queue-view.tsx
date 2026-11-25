"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "motion/react";
import { ArrowRight, Check, ChevronDown, ClipboardCheck, Loader2, Lock, MessageSquareWarning, SkipForward } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { EmptyState } from "@/components/shared/empty-state";
import { PageHeader, SectionHeading } from "@/components/shared/page-header";
import { ErrorState, errorMessage } from "@/components/shared/query-state";
import { StatusBadge } from "@/components/shared/status-badge";
import { Surface } from "@/components/shared/surface";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api/endpoints";
import { formatNumber, formatRelative, humanize } from "@/lib/formatting";
import { cn } from "@/lib/utils";

import { OpenEmployerButton, PROVENANCE, useInvalidateApplications, type Application } from "./shared";

const LIMIT = 200;

export function ReviewQueueView() {
  const ready = useQuery({
    queryKey: ["applications", "list", { status: "READY_FOR_REVIEW", limit: LIMIT, offset: 0 }],
    queryFn: () => api.applications({ status: "READY_FOR_REVIEW", limit: LIMIT }),
  });
  const approved = useQuery({
    queryKey: ["applications", "list", { status: "APPROVED", limit: LIMIT, offset: 0 }],
    queryFn: () => api.applications({ status: "APPROVED", limit: LIMIT }),
  });

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow="Pipeline"
        title="Review queue"
        description="Prepared applications waiting for your judgement. Read the letter and answers, then approve or skip. Approving never sends anything."
        actions={
          <Button asChild variant="outline">
            <Link href="/applications">All applications</Link>
          </Button>
        }
      />

      <section aria-label="Ready for review">
        <SectionHeading
          title="Ready for review"
          description={ready.data ? `${formatNumber(ready.data.total)} waiting` : undefined}
        />
        {ready.isPending ? (
          <ListSkeleton />
        ) : ready.isError ? (
          <ErrorState error={ready.error} onRetry={() => void ready.refetch()} />
        ) : ready.data.items.length === 0 ? (
          <EmptyState
            icon={ClipboardCheck}
            title="Nothing to review"
            description="Prepared applications land here. Prepare one from Job discovery or run auto-apply."
            action={
              <Button asChild size="sm">
                <Link href="/jobs">Find jobs</Link>
              </Button>
            }
          />
        ) : (
          <>
            <ul className="space-y-3">
              <AnimatePresence initial={false}>
                {ready.data.items.map((item) => (
                  <motion.li
                    key={item.id}
                    layout
                    initial={{ opacity: 0, y: 6 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, height: 0, marginTop: 0 }}
                    transition={{ duration: 0.24, ease: [0.22, 1, 0.36, 1] }}
                  >
                    <ReviewCard item={item} />
                  </motion.li>
                ))}
              </AnimatePresence>
            </ul>
            {ready.data.total > ready.data.items.length ? (
              <p className="mt-3 text-center text-xs text-text-3">
                Showing {formatNumber(ready.data.items.length)} of {formatNumber(ready.data.total)}.
              </p>
            ) : null}
          </>
        )}
      </section>

      <section aria-label="Approved">
        <SectionHeading
          title="Approved — submit these yourself"
          description="JobOrbit does not send approved applications. Open the employer's page, submit there, then record it on the application."
        />
        {approved.isPending ? (
          <ListSkeleton rows={2} />
        ) : approved.isError ? (
          <ErrorState error={approved.error} onRetry={() => void approved.refetch()} />
        ) : approved.data.items.length === 0 ? (
          <EmptyState compact icon={Check} title="No approved applications waiting" />
        ) : (
          <ul className="grid gap-3 md:grid-cols-2">
            {approved.data.items.map((item) => (
              <li key={item.id}>
                <Surface className="flex h-full flex-col gap-3 p-4">
                  <Heading item={item} />
                  {item.next_action ? <p className="text-xs text-text-2">{item.next_action}</p> : null}
                  <div className="mt-auto flex flex-wrap gap-2">
                    <OpenEmployerButton application={item} />
                    <Button asChild size="sm" variant="ghost">
                      <Link href={`/applications/${item.id}`}>
                        Record outcome <ArrowRight />
                      </Link>
                    </Button>
                  </div>
                </Surface>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function Heading({ item }: { item: Application }) {
  return (
    <div className="min-w-0">
      <p className="truncate text-[11px] font-medium uppercase tracking-wide text-text-3">{item.job_company || "—"}</p>
      <Link href={`/applications/${item.id}`} className="line-clamp-2 font-heading text-[15px] font-semibold text-text-1 hover:text-violet">
        {item.job_title || `Job ${item.job_id}`}
      </Link>
      <p className="text-[11px] text-text-3">
        {humanize(item.platform)} · prepared {formatRelative(item.prepared_at)}
        {item.employer_page_opened ? " · employer page opened" : ""}
      </p>
    </div>
  );
}

function ReviewCard({ item }: { item: Application }) {
  const queryClient = useQueryClient();
  const invalidate = useInvalidateApplications();
  const [letterOpen, setLetterOpen] = useState(false);
  const [answersOpen, setAnswersOpen] = useState(false);
  const blocking = item.blocking_questions ?? [];
  const answers = item.answers ?? [];

  const act = useMutation({
    mutationFn: (action: "approve" | "skip") =>
      api.updateApplication(
        item.id,
        action === "approve" ? { status: "APPROVED", user_approved: true } : { status: "SKIPPED" },
      ),
    onSuccess: (next, action) => {
      queryClient.setQueryData(["applications", "detail", item.id], next);
      invalidate();
      toast.success(action === "approve" ? "Approved" : "Skipped", {
        description: `${item.job_title} at ${item.job_company}`,
      });
    },
  });

  return (
    <Surface className="overflow-hidden">
      <div className="flex flex-col gap-3 p-4 sm:flex-row sm:items-start">
        <div className="min-w-0 flex-1 space-y-2">
          <Heading item={item} />
          <div className="flex flex-wrap gap-1.5">
            {blocking.length ? (
              <StatusBadge tone="warning" dot={false}>
                <MessageSquareWarning className="size-3" /> {blocking.length} question(s) to answer
              </StatusBadge>
            ) : (
              <StatusBadge tone="success">No open questions</StatusBadge>
            )}
            <StatusBadge tone="neutral" dot={false}>
              {answers.length} answer(s)
            </StatusBadge>
          </div>
          {blocking.length ? (
            <ul className="list-disc space-y-0.5 pl-4 text-xs text-text-2">
              {blocking.map((question) => (
                <li key={question}>{question}</li>
              ))}
            </ul>
          ) : null}
        </div>
        <div className="flex shrink-0 flex-wrap gap-2 sm:flex-col sm:items-stretch">
          <Button
            disabled={act.isPending || blocking.length > 0}
            title={blocking.length ? "Answer the open questions first" : undefined}
            onClick={() => act.mutate("approve")}
          >
            {act.isPending && act.variables === "approve" ? <Loader2 className="animate-spin" /> : <Check />} Approve
          </Button>
          <Button variant="outline" disabled={act.isPending} onClick={() => act.mutate("skip")}>
            {act.isPending && act.variables === "skip" ? <Loader2 className="animate-spin" /> : <SkipForward />} Skip
          </Button>
          <Button asChild variant="ghost">
            <Link href={`/applications/${item.id}`}>
              Open <ArrowRight />
            </Link>
          </Button>
        </div>
      </div>

      {act.isError ? (
        <p role="alert" className="mx-4 mb-3 rounded-lg bg-danger-soft px-3 py-2 text-xs text-text-1">
          {errorMessage(act.error)}
        </p>
      ) : null}
      {blocking.length ? (
        <p className="mx-4 mb-3 text-xs text-text-3">
          Sensitive and legal questions are never drafted for you.{" "}
          <Link href="/action-inbox" className="text-violet hover:underline">
            Answer them in the Action inbox
          </Link>
          .
        </p>
      ) : null}

      <div className="border-t border-line">
        <Disclosure open={letterOpen} onToggle={() => setLetterOpen((value) => !value)} label="Cover letter">
          {item.cover_letter ? (
            <p className="whitespace-pre-line text-xs leading-relaxed text-text-2">{item.cover_letter}</p>
          ) : (
            <p className="text-xs text-text-3">No cover letter.</p>
          )}
        </Disclosure>
        {!letterOpen && item.cover_letter ? (
          <div className="border-b border-line px-4 pb-3">
            <p className="line-clamp-2 text-xs leading-relaxed text-text-3">{item.cover_letter}</p>
          </div>
        ) : null}
        <Disclosure open={answersOpen} onToggle={() => setAnswersOpen((value) => !value)} label={`Answers (${answers.length})`}>
          {answers.length ? (
            <dl className="divide-y divide-line">
              {answers.map((answer) => {
                const provenance = PROVENANCE[answer.provenance];
                return (
                  <div key={answer.id} className="grid gap-1 py-1.5 text-xs sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_7rem] sm:gap-3">
                    <dt className="text-text-2">{answer.question}</dt>
                    <dd className="break-words text-text-1">
                      {answer.answer?.trim() ? (
                        <span className="inline-flex items-center gap-1">
                          {answer.is_sensitive ? <Lock className="size-3 shrink-0 text-text-3" /> : null}
                          {answer.answer}
                        </span>
                      ) : (
                        <span className="text-warning">Not answered</span>
                      )}
                    </dd>
                    <dd>
                      <StatusBadge tone={provenance?.tone ?? "neutral"}>{provenance?.label ?? humanize(answer.provenance)}</StatusBadge>
                    </dd>
                  </div>
                );
              })}
            </dl>
          ) : (
            <p className="text-xs text-text-3">No answers prepared.</p>
          )}
        </Disclosure>
      </div>
    </Surface>
  );
}

function Disclosure({
  open,
  onToggle,
  label,
  children,
}: {
  open: boolean;
  onToggle: () => void;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="border-b border-line last:border-b-0">
      <button
        type="button"
        aria-expanded={open}
        onClick={onToggle}
        className="flex w-full items-center gap-2 px-4 py-2 text-left text-xs font-medium text-text-2 transition-colors hover:bg-surface-2/50 hover:text-text-1"
      >
        <ChevronDown className={cn("size-3.5 transition-transform duration-200", !open && "-rotate-90")} />
        {label}
      </button>
      <AnimatePresence initial={false}>
        {open ? (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2, ease: [0.22, 1, 0.36, 1] }}
            className="overflow-hidden"
          >
            <div className="px-4 pb-3">{children}</div>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </div>
  );
}

function ListSkeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="space-y-3">
      {Array.from({ length: rows }).map((_, index) => (
        <Skeleton key={index} className="h-36 w-full rounded-xl" />
      ))}
    </div>
  );
}
