"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import {
  ArrowRight,
  Bot,
  Check,
  CircleSlash,
  History,
  Loader2,
  Mic,
  SkipForward,
  X,
} from "lucide-react";
import { useId, useState } from "react";
import { toast } from "sonner";

import { EmptyState } from "@/components/shared/empty-state";
import { errorMessage } from "@/components/shared/query-state";
import { StatusBadge } from "@/components/shared/status-badge";
import { Surface } from "@/components/shared/surface";
import { Button } from "@/components/ui/button";
import { Kbd } from "@/components/ui/kbd";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import type { Schemas } from "@/lib/api/client";
import { api } from "@/lib/api/endpoints";
import { formatDateTime } from "@/lib/formatting";
import { cn } from "@/lib/utils";

import {
  PRACTICE_KINDS,
  sectionLabel,
  type PracticeEntry,
  type PracticeFeedback,
  type PrepItem,
} from "./research-types";

const STAR_LABEL: Record<string, string> = { situation: "Situation", task: "Task", action: "Action", result: "Result" };

function wordCount(text: string): number {
  const trimmed = text.trim();
  return trimmed ? trimmed.split(/\s+/).length : 0;
}

function CheckChip({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] ring-1 ring-inset",
        ok ? "bg-success-soft text-success ring-success/25" : "bg-surface-2 text-text-3 ring-line",
      )}
    >
      {ok ? <Check className="size-3" /> : <X className="size-3" />}
      {label}
    </span>
  );
}

export function FeedbackPanel({ feedback, compact }: { feedback: PracticeFeedback; compact?: boolean }) {
  const checks = feedback.checks ?? {};
  return (
    <div className={cn("space-y-3", !compact && "rounded-xl border border-violet/25 bg-violet-soft/40 p-4")}>
      {!compact ? (
        <div className="flex flex-wrap items-center gap-2">
          <Bot className="size-4 text-violet" />
          <p className="font-heading text-sm font-semibold text-text-1">Rule-based feedback</p>
          <StatusBadge tone="warning" dot={false}>
            Automatic · not a human grade
          </StatusBadge>
        </div>
      ) : null}
      <ul className="space-y-1.5">
        {(feedback.points ?? []).map((point, index) => (
          <li key={index} className="flex gap-2 text-[13px] leading-relaxed text-text-1">
            <ArrowRight className="mt-1 size-3 shrink-0 text-violet" aria-hidden />
            <span>{point}</span>
          </li>
        ))}
      </ul>
      <div className="flex flex-wrap gap-1.5">
        {typeof checks.word_count === "number" ? (
          <span className="tabular inline-flex items-center rounded-md bg-surface-2 px-1.5 py-0.5 text-[11px] text-text-2 ring-1 ring-inset ring-line">
            {checks.word_count} words
          </span>
        ) : null}
        {checks.star
          ? Object.entries(checks.star).map(([part, ok]) => (
              <CheckChip key={part} ok={ok} label={STAR_LABEL[part] ?? part} />
            ))
          : null}
        {typeof checks.has_example === "boolean" ? <CheckChip ok={checks.has_example} label="Concrete example" /> : null}
        {typeof checks.has_numbers === "boolean" ? <CheckChip ok={checks.has_numbers} label="Numbers" /> : null}
        {checks.skills_mentioned?.length ? (
          <span className="inline-flex items-center rounded-md bg-cyan-soft px-1.5 py-0.5 text-[11px] text-cyan ring-1 ring-inset ring-cyan/25">
            Skills named: {checks.skills_mentioned.slice(0, 5).join(", ")}
          </span>
        ) : null}
      </div>
      {feedback.disclaimer ? <p className="text-[11.5px] leading-relaxed text-text-3">{feedback.disclaimer}</p> : null}
    </div>
  );
}

/**
 * One question at a time from the prep's practisable sections. Feedback comes from fixed
 * rules (length, STAR structure, skills named, an example, numbers) and says so.
 */
export function MockInterview({
  applicationId,
  initialQuestion,
  practice,
}: {
  applicationId: number;
  initialQuestion: PrepItem | null;
  practice: PracticeEntry[];
}) {
  const id = useId();
  const client = useQueryClient();
  const reduced = useReducedMotion();
  const [question, setQuestion] = useState<PrepItem | null>(initialQuestion);
  const [kind, setKind] = useState<string>("");
  const [answer, setAnswer] = useState("");
  const [result, setResult] = useState<Schemas["PracticeResult"] | null>(null);

  const next = useMutation({
    mutationFn: (args: { kind?: string; after?: string }) => api.nextPracticeQuestion(applicationId, args),
    onSuccess: (data) => {
      setQuestion((data.question as unknown as PrepItem | null) ?? null);
      setAnswer("");
      setResult(null);
    },
    onError: (error) => toast.error("Could not load the next question", { description: errorMessage(error) }),
  });

  const record = useMutation({
    mutationFn: () => api.recordPractice(applicationId, { question_id: question!.id, answer }),
    onSuccess: (data) => {
      setResult(data);
      void client.invalidateQueries({ queryKey: ["interview-prep", applicationId] });
    },
    onError: (error) => toast.error("The answer was not recorded", { description: errorMessage(error) }),
  });

  const words = wordCount(answer);
  const history = [...practice].reverse();

  const goNext = () => {
    if (result?.next_question && !kind) {
      setQuestion(result.next_question as unknown as PrepItem);
      setAnswer("");
      setResult(null);
      return;
    }
    next.mutate({ kind: kind || undefined, after: question?.id });
  };

  return (
    <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]">
      <div className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <ToggleGroup
            type="single"
            variant="outline"
            size="sm"
            value={kind || "all"}
            onValueChange={(value) => {
              if (!value) return;
              const nextKind = value === "all" ? "" : value;
              setKind(nextKind);
              next.mutate({ kind: nextKind || undefined });
            }}
            aria-label="Question type"
          >
            <ToggleGroupItem value="all">Mixed</ToggleGroupItem>
            {PRACTICE_KINDS.map((section) => (
              <ToggleGroupItem key={section.key} value={section.key}>
                {section.label}
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
          <p className="text-[11px] text-text-3">Unpractised questions come first.</p>
        </div>

        {!question ? (
          <EmptyState
            icon={CircleSlash}
            title="No question to practise"
            description={
              kind
                ? `This preparation has no ${sectionLabel(kind).toLowerCase()} questions.`
                : "This preparation has no technical, resume, project or behavioural questions."
            }
          />
        ) : (
          <AnimatePresence mode="wait" initial={false}>
            <motion.div
              key={question.id}
              initial={reduced ? false : { opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={reduced ? undefined : { opacity: 0, y: -6 }}
              transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
            >
              <Surface className="space-y-4 p-5">
                <div className="flex flex-wrap items-center gap-2">
                  <StatusBadge tone="violet">{sectionLabel(question.kind)}</StatusBadge>
                  <span className="text-[11px] text-text-3">
                    {question.times_practised ? `practised ${question.times_practised}× before` : "not practised yet"}
                  </span>
                </div>
                <p className="font-heading text-lg leading-snug font-medium text-text-1">{question.question}</p>
                <p className="text-xs text-text-3">Derived from {question.derived_from}</p>

                {result ? (
                  <div className="space-y-3">
                    <details className="rounded-lg border border-line bg-surface-2/40 p-3">
                      <summary className="cursor-pointer text-xs text-text-2">Your answer ({words} words)</summary>
                      <p className="mt-2 text-sm whitespace-pre-wrap text-text-1">{answer}</p>
                    </details>
                    <FeedbackPanel feedback={result.feedback as unknown as PracticeFeedback} />
                    <div className="flex flex-wrap items-center gap-2">
                      <Button onClick={goNext} disabled={next.isPending}>
                        {next.isPending ? <Loader2 className="animate-spin" /> : <ArrowRight />}
                        Next question
                      </Button>
                      <Button
                        variant="ghost"
                        onClick={() => {
                          setResult(null);
                        }}
                      >
                        Try this one again
                      </Button>
                    </div>
                  </div>
                ) : (
                  <form
                    className="space-y-3"
                    onSubmit={(event) => {
                      event.preventDefault();
                      if (answer.trim()) record.mutate();
                    }}
                  >
                    <div className="space-y-1.5">
                      <div className="flex items-end justify-between gap-2">
                        <Label htmlFor={`${id}-answer`}>Your answer</Label>
                        <span
                          className={cn(
                            "tabular text-[11px]",
                            words === 0 ? "text-text-3" : words < 40 || words > 350 ? "text-warning" : "text-success",
                          )}
                          aria-live="polite"
                        >
                          {words} words · aim for 80–250
                        </span>
                      </div>
                      <Textarea
                        id={`${id}-answer`}
                        value={answer}
                        onChange={(event) => setAnswer(event.target.value)}
                        onKeyDown={(event) => {
                          if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
                            event.preventDefault();
                            if (answer.trim()) record.mutate();
                          }
                        }}
                        rows={8}
                        maxLength={5000}
                        placeholder="Answer as you would out loud. Say what you did, how, and what happened."
                        className="min-h-40 resize-y"
                      />
                    </div>
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        onClick={() => next.mutate({ kind: kind || undefined, after: question.id })}
                        disabled={next.isPending}
                      >
                        {next.isPending ? <Loader2 className="animate-spin" /> : <SkipForward />}
                        Skip
                      </Button>
                      <div className="flex items-center gap-2">
                        <span className="hidden items-center gap-1 text-[11px] text-text-3 sm:flex">
                          <Kbd>⌘</Kbd>
                          <Kbd>Enter</Kbd>
                        </span>
                        <Button type="submit" disabled={!answer.trim() || record.isPending}>
                          {record.isPending ? <Loader2 className="animate-spin" /> : <Mic />}
                          Get feedback
                        </Button>
                      </div>
                    </div>
                  </form>
                )}
              </Surface>
            </motion.div>
          </AnimatePresence>
        )}
      </div>

      <Surface className="p-4">
        <div className="mb-3 flex items-center gap-2">
          <History className="size-3.5 text-text-3" />
          <h3 className="font-heading text-sm font-semibold text-text-1">Practice history</h3>
          <span className="tabular ml-auto text-[11px] text-text-3">{practice.length}</span>
        </div>
        {history.length ? (
          <ul className="max-h-[32rem] space-y-2 overflow-y-auto pr-1">
            {history.map((entry, index) => (
              <li key={`${entry.question_id}-${entry.answered_at}-${index}`}>
                <details className="group rounded-lg border border-line p-2.5 open:bg-surface-2/40">
                  <summary className="cursor-pointer list-none space-y-0.5">
                    <p className="line-clamp-2 text-xs text-text-1">{entry.question}</p>
                    <p className="text-[10.5px] text-text-3">
                      {sectionLabel(entry.kind)} · {formatDateTime(entry.answered_at)}
                    </p>
                  </summary>
                  <div className="mt-2 space-y-2 border-t border-line pt-2">
                    <p className="line-clamp-6 text-xs whitespace-pre-wrap text-text-2">
                      {entry.answer || <span className="italic text-text-3">No answer given</span>}
                    </p>
                    <FeedbackPanel feedback={entry.feedback} compact />
                  </div>
                </details>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-xs text-text-3">Answers you practise are kept here with their feedback.</p>
        )}
      </Surface>
    </div>
  );
}
