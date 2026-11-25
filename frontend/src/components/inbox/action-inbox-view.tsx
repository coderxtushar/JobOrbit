"use client";

import { useQuery } from "@tanstack/react-query";
import { BookMarked, CheckCheck, CircleCheck, Inbox, Lock, MessageSquareText, RotateCw, ShieldCheck, Sparkles } from "lucide-react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useState } from "react";

import { EmptyState } from "@/components/shared/empty-state";
import { PageHeader, SectionHeading } from "@/components/shared/page-header";
import { ErrorState } from "@/components/shared/query-state";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api } from "@/lib/api/endpoints";
import type { Schemas } from "@/lib/api/client";
import { formatNumber } from "@/lib/formatting";

import { AnswerBank } from "./answer-bank";
import { InboxEntryCard } from "./inbox-entry-card";

type Entry = Schemas["InboxEntryRead"];

interface Resolved {
  key: string;
  question: string;
  filled: number;
  applied: boolean;
}

const PRINCIPLES = [
  {
    icon: ShieldCheck,
    title: "Never guessed",
    body: "A question lands here only when nothing verified answers it. JobOrbit leaves it blank rather than invent a reply.",
  },
  {
    icon: Lock,
    title: "Sensitive is never drafted",
    body: "Salary, notice period, work authorisation, declarations and similar are answered only by you, never by a model.",
  },
  {
    icon: CheckCheck,
    title: "Answer once, fill everywhere",
    body: "Your answer is saved to the bank and applied to every open application waiting on it. Submitted ones are never rewritten.",
  },
];

export function ActionInboxView() {
  const inbox = useQuery({ queryKey: ["inbox"], queryFn: () => api.inbox(200) });
  const answers = useQuery({ queryKey: ["answers"], queryFn: api.answers });
  const [resolved, setResolved] = useState<Resolved[]>([]);
  const reduced = useReducedMotion();

  const entries = inbox.data ?? [];
  const sensitive = entries.filter((entry) => entry.is_sensitive);
  const other = entries.filter((entry) => !entry.is_sensitive);
  const waitingApplications = entries.reduce((sum, entry) => sum + entry.occurrences, 0);

  const onResolved = (result: Schemas["ResolveResponse"], entry: Entry) =>
    setResolved((current) => [
      {
        key: result.question_key,
        question: entry.question,
        filled: result.applications_updated,
        applied: result.applications_updated > 0,
      },
      ...current.filter((item) => item.key !== result.question_key),
    ]);

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow="Needs you"
        title="Action inbox"
        description="Questions only you can answer. Answer each once and it fills every open application that was waiting on it."
        actions={
          <Button variant="outline" size="sm" onClick={() => inbox.refetch()} disabled={inbox.isFetching}>
            <RotateCw className={inbox.isFetching ? "animate-spin" : undefined} /> Refresh
          </Button>
        }
      />

      <div className="grid gap-3 md:grid-cols-3">
        {PRINCIPLES.map(({ icon: Icon, title, body }) => (
          <div key={title} className="flex gap-3 rounded-xl border border-line bg-surface-1/60 p-4">
            <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-violet-soft text-violet ring-1 ring-inset ring-violet/20">
              <Icon className="size-4" />
            </span>
            <div className="space-y-1">
              <p className="text-sm font-medium text-text-1">{title}</p>
              <p className="text-xs leading-relaxed text-text-3">{body}</p>
            </div>
          </div>
        ))}
      </div>

      <Tabs defaultValue="waiting" className="gap-5">
        <TabsList>
          <TabsTrigger value="waiting" className="px-3">
            <Inbox /> Waiting on you
            {inbox.data ? (
              <span className="ml-1 rounded-full bg-warning-soft px-1.5 text-[11px] text-warning tabular">
                {formatNumber(entries.length)}
              </span>
            ) : null}
          </TabsTrigger>
          <TabsTrigger value="bank" className="px-3">
            <BookMarked /> Answer bank
            {answers.data ? (
              <span className="ml-1 rounded-full bg-surface-3 px-1.5 text-[11px] text-text-2 tabular">
                {formatNumber(answers.data.length)}
              </span>
            ) : null}
          </TabsTrigger>
        </TabsList>

        <TabsContent value="waiting" className="space-y-8">
          <AnimatePresence initial={false}>
            {resolved.length ? (
              <motion.section
                initial={reduced ? false : { opacity: 0, y: -6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
                aria-live="polite"
                className="rounded-xl border border-success/25 bg-success-soft p-4"
              >
                <div className="mb-2 flex items-center justify-between gap-3">
                  <p className="inline-flex items-center gap-2 text-sm font-medium text-text-1">
                    <CircleCheck className="size-4 text-success" /> Answered this session
                  </p>
                  <Button size="xs" variant="ghost" onClick={() => setResolved([])}>
                    Clear
                  </Button>
                </div>
                <ul className="space-y-1.5">
                  {resolved.map((item) => (
                    <li key={item.key} className="flex flex-col gap-0.5 text-xs sm:flex-row sm:items-baseline sm:justify-between sm:gap-4">
                      <span className="truncate text-text-1">{item.question}</span>
                      <span className="shrink-0 text-text-2 tabular">
                        {item.applied
                          ? `Filled ${formatNumber(item.filled)} application${item.filled === 1 ? "" : "s"}`
                          : "Saved to the bank; no open application filled"}
                      </span>
                    </li>
                  ))}
                </ul>
              </motion.section>
            ) : null}
          </AnimatePresence>

          {inbox.isLoading ? (
            <div className="space-y-3">
              <Skeleton className="h-5 w-48" />
              {Array.from({ length: 3 }).map((_, index) => (
                <Skeleton key={index} className="h-52 w-full rounded-xl" />
              ))}
            </div>
          ) : inbox.isError ? (
            <ErrorState error={inbox.error} onRetry={() => inbox.refetch()} />
          ) : entries.length === 0 ? (
            <EmptyState
              icon={Sparkles}
              title="Nothing is waiting on you"
              description="Every prepared application has an answer for each question it asks. When a new one needs something only you know, it will appear here."
            />
          ) : (
            <>
              <p className="text-sm text-text-2">
                <span className="font-medium text-text-1 tabular">{formatNumber(entries.length)}</span> question
                {entries.length === 1 ? "" : "s"} across{" "}
                <span className="font-medium text-text-1 tabular">{formatNumber(waitingApplications)}</span> application
                answer{waitingApplications === 1 ? "" : "s"}, most frequent first.
              </p>
              {sensitive.length ? (
                <EntryGroup
                  title="Sensitive — only you can answer"
                  description="Legal, financial or personal questions. These are never drafted, by a model or by a template."
                  icon={Lock}
                  entries={sensitive}
                  onResolved={onResolved}
                />
              ) : null}
              {other.length ? (
                <EntryGroup
                  title="Other questions"
                  description="Your profile has no verified answer for these, so they are left for you rather than guessed."
                  icon={MessageSquareText}
                  entries={other}
                  onResolved={onResolved}
                />
              ) : null}
            </>
          )}
        </TabsContent>

        <TabsContent value="bank">
          <SectionHeading
            title="Answer bank"
            description="Reusable answers you have given. Each keeps where it came from; AI drafts are never stored here."
          />
          <AnswerBank />
        </TabsContent>
      </Tabs>
    </div>
  );
}

function EntryGroup({
  title,
  description,
  icon: Icon,
  entries,
  onResolved,
}: {
  title: string;
  description: string;
  icon: typeof Lock;
  entries: Entry[];
  onResolved: (result: Schemas["ResolveResponse"], entry: Entry) => void;
}) {
  const reduced = useReducedMotion();
  return (
    <section aria-label={title}>
      <div className="mb-3 flex items-start gap-2.5">
        <Icon className="mt-0.5 size-4 shrink-0 text-text-3" />
        <SectionHeading title={`${title} (${entries.length})`} description={description} />
      </div>
      <ul className="grid gap-3 xl:grid-cols-2">
        <AnimatePresence initial={false}>
          {entries.map((entry, index) => (
            <motion.li
              key={entry.question_key}
              layout={!reduced}
              initial={reduced ? false : { opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={reduced ? { opacity: 0 } : { opacity: 0, scale: 0.98 }}
              transition={{ duration: 0.25, delay: Math.min(index, 6) * 0.03, ease: [0.22, 1, 0.36, 1] }}
            >
              <InboxEntryCard entry={entry} onResolved={onResolved} />
            </motion.li>
          ))}
        </AnimatePresence>
      </ul>
    </section>
  );
}
