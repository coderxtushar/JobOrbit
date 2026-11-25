"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, Info, Loader2, Lock, ShieldAlert, Sparkles } from "lucide-react";
import Link from "next/link";
import { useId, useState } from "react";
import { toast } from "sonner";

import { errorMessage } from "@/components/shared/query-state";
import { StatusBadge } from "@/components/shared/status-badge";
import { Surface } from "@/components/shared/surface";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api/endpoints";
import type { Schemas } from "@/lib/api/client";
import { formatNumber } from "@/lib/formatting";
import { cn } from "@/lib/utils";

import { fallbackReason } from "./labels";

type Entry = Schemas["InboxEntryRead"];
type Resolve = Schemas["ResolveResponse"];

/**
 * One outstanding question. The reason it was flagged is not part of the inbox response, so
 * it is read from the first waiting application only when the user opens "Why".
 */
interface Choices {
  /** The question without the "(choose one of: …)" suffix the backend appends. */
  prompt: string;
  options: string[];
  multiple: boolean;
  /** The form offers more options than the question text lists (e.g. a country list). */
  truncated: boolean;
}

/**
 * The backend phrases a choice question as "Label (choose one of: A / B / C)" or
 * "(choose any of, separated by ;: …)", listing up to 15 options. Reading them back lets
 * the answer be picked rather than typed, so it always matches an option exactly.
 */
function parseChoices(question: string): Choices | null {
  const match = question.match(
    /^([\s\S]*?)\s*\(choose (one|any) of(?:, separated by ;)?: ([\s\S]*)\)\s*(?:—[\s\S]*)?$/,
  );
  if (!match) return null;
  let list = match[3];
  const more = /\s*\/\s*… and \d+ more$/.exec(list);
  if (more) list = list.slice(0, more.index);
  const options = list.split(" / ").map((item) => item.trim()).filter(Boolean);
  if (!options.length) return null;
  return { prompt: match[1].trim(), options, multiple: match[2] === "any", truncated: Boolean(more) };
}

export function InboxEntryCard({
  entry,
  onResolved,
}: {
  entry: Entry;
  onResolved: (result: Resolve, entry: Entry) => void;
}) {
  const queryClient = useQueryClient();
  const fieldId = useId();
  const [answer, setAnswer] = useState("");
  const [applyToOpen, setApplyToOpen] = useState(true);
  const [showWhy, setShowWhy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const ids = entry.application_ids ?? [];
  const firstId = ids.length ? Number(ids[0]) : null;

  const detail = useQuery({
    queryKey: ["applications", "detail", firstId],
    queryFn: () => api.application(firstId as number),
    enabled: showWhy && firstId !== null,
    staleTime: 60_000,
  });
  const flagged = detail.data?.answers?.find((item) => item.question_key === entry.question_key);
  const reason = flagged?.flag_reason?.trim() || null;

  const save = useMutation({
    mutationFn: () =>
      api.saveAnswer(entry.question_key, {
        answer: answer.trim(),
        question: entry.question,
        apply_to_open_applications: applyToOpen,
      }),
    onSuccess: (result) => {
      setError(null);
      const filled = result.applications_updated;
      toast.success("Answer saved to your bank", {
        description: applyToOpen
          ? `Filled ${formatNumber(filled)} open application${filled === 1 ? "" : "s"}.`
          : "Not applied to open applications, as you chose.",
      });
      onResolved(result, entry);
      void queryClient.invalidateQueries({ queryKey: ["inbox"] });
      void queryClient.invalidateQueries({ queryKey: ["nav", "inbox"] });
      void queryClient.invalidateQueries({ queryKey: ["answers"] });
    },
    onError: (failure) => setError(errorMessage(failure)),
  });

  const trimmed = answer.trim();
  const choices = parseChoices(entry.question);
  const pickable = choices !== null && !choices.truncated;
  const picked = choices?.multiple
    ? answer.split(";").map((item) => item.trim()).filter(Boolean)
    : [trimmed];
  const toggle = (option: string) => {
    if (error) setError(null);
    if (!choices?.multiple) {
      setAnswer(option);
      return;
    }
    const next = picked.includes(option) ? picked.filter((item) => item !== option) : [...picked, option];
    setAnswer(next.join("; "));
  };

  return (
    <Surface className="group/entry overflow-hidden p-0 transition-[border-color,box-shadow] duration-200 focus-within:border-line-strong hover:border-line-strong">
      <div className="flex flex-col gap-4 p-4 sm:p-5">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0 space-y-1.5">
            <p className="font-heading text-[15px] leading-snug font-medium text-text-1">
              {choices?.prompt || entry.question}
            </p>
            <p className="truncate font-mono text-[11px] text-text-3">{entry.question_key}</p>
          </div>
          <div className="flex shrink-0 flex-wrap items-center gap-1.5 sm:justify-end">
            {entry.is_sensitive ? (
              <StatusBadge tone="warning">
                <Lock className="size-3" /> Sensitive
              </StatusBadge>
            ) : null}
            {entry.has_saved_answer ? (
              <StatusBadge tone="cyan">In your bank, still open</StatusBadge>
            ) : null}
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-text-2">
          <span className="inline-flex items-center gap-1.5">
            <span className="font-heading text-base font-semibold text-text-1 tabular">
              {formatNumber(entry.occurrences)}
            </span>
            application{entry.occurrences === 1 ? "" : "s"} waiting on this
          </span>
          {ids.length ? (
            <span className="inline-flex flex-wrap items-center gap-1">
              {ids.map((id) => (
                <Link
                  key={id}
                  href={`/applications/${id}`}
                  className="rounded-md bg-surface-2 px-1.5 py-0.5 font-mono text-[11px] text-text-2 ring-1 ring-inset ring-line transition-colors hover:bg-surface-3 hover:text-text-1"
                >
                  #{id}
                </Link>
              ))}
              {entry.occurrences > ids.length ? (
                <span className="text-text-3">
                  showing {ids.length} of {formatNumber(entry.occurrences)}
                </span>
              ) : null}
            </span>
          ) : null}
        </div>

        <Collapsible open={showWhy} onOpenChange={setShowWhy}>
          <CollapsibleTrigger asChild>
            <button
              type="button"
              className="inline-flex items-center gap-1.5 rounded-md text-xs font-medium text-text-2 transition-colors hover:text-text-1"
            >
              <Info className="size-3.5" />
              Why you are being asked
              <ChevronDown className={cn("size-3.5 transition-transform duration-200", showWhy && "rotate-180")} />
            </button>
          </CollapsibleTrigger>
          <CollapsibleContent className="data-[state=open]:animate-in data-[state=open]:fade-in-0">
            <div className="mt-2 rounded-lg border border-line bg-surface-2/60 p-3 text-xs leading-relaxed text-text-2">
              {detail.isLoading ? (
                <div className="space-y-1.5">
                  <Skeleton className="h-3 w-full" />
                  <Skeleton className="h-3 w-2/3" />
                </div>
              ) : (
                <>
                  <p>{reason ?? fallbackReason(entry.is_sensitive)}</p>
                  {reason && firstId !== null ? (
                    <p className="mt-1.5 text-[11px] text-text-3">Flag reason recorded on application #{firstId}.</p>
                  ) : null}
                  {entry.is_sensitive ? (
                    <p className="mt-2 inline-flex items-center gap-1.5 text-[11px] text-warning">
                      <ShieldAlert className="size-3" /> Sensitive questions are never drafted, only answered by you.
                    </p>
                  ) : null}
                </>
              )}
            </div>
          </CollapsibleContent>
        </Collapsible>
      </div>

      <form
        className="space-y-3 border-t border-line bg-surface-2/35 p-4 sm:p-5"
        onSubmit={(event) => {
          event.preventDefault();
          if (!trimmed) {
            setError("Type an answer first. A blank answer cannot be saved.");
            return;
          }
          save.mutate();
        }}
      >
        {pickable ? (
          <div className="space-y-1.5">
            <p className="text-xs text-text-2">
              {choices.multiple ? "Pick every option that applies" : "Pick the option the employer offers"}
            </p>
            <div role={choices.multiple ? "group" : "radiogroup"} aria-label="Options" className="flex flex-wrap gap-1.5">
              {choices.options.map((option) => {
                const on = picked.includes(option);
                return (
                  <button
                    key={option}
                    type="button"
                    role={choices.multiple ? "checkbox" : "radio"}
                    aria-checked={on}
                    onClick={() => toggle(option)}
                    className={cn(
                      "rounded-lg px-3 py-1.5 text-left text-[13px] ring-1 ring-inset transition-colors",
                      on
                        ? "bg-violet-soft text-violet ring-violet/40"
                        : "bg-surface-1 text-text-2 ring-line hover:text-text-1 hover:ring-line-strong",
                    )}
                  >
                    {option}
                  </button>
                );
              })}
            </div>
            {error ? (
              <p role="alert" className="text-xs text-danger">
                {error}
              </p>
            ) : null}
          </div>
        ) : (
        <div className="space-y-1.5">
          <Label htmlFor={`${fieldId}-answer`} className="text-xs text-text-2">
            Your answer
          </Label>
          {choices?.truncated ? (
            <p className="text-[11px] text-text-3">
              The form offers more options than listed here. Type one exactly as the employer
              writes it, for example “{choices.options[0]}”.
            </p>
          ) : null}
          <Textarea
            id={`${fieldId}-answer`}
            value={answer}
            onChange={(event) => {
              setAnswer(event.target.value);
              if (error) setError(null);
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter" && (event.metaKey || event.ctrlKey) && trimmed) {
                event.preventDefault();
                save.mutate();
              }
            }}
            rows={2}
            placeholder={entry.is_sensitive ? "Only you can answer this" : "Type the answer you want employers to receive"}
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? `${fieldId}-error` : undefined}
            className="min-h-16 resize-y bg-surface-1"
          />
          {error ? (
            <p id={`${fieldId}-error`} role="alert" className="text-xs text-danger">
              {error}
            </p>
          ) : null}
        </div>
        )}
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-2">
            <Switch id={`${fieldId}-apply`} checked={applyToOpen} onCheckedChange={setApplyToOpen} />
            <Label htmlFor={`${fieldId}-apply`} className="text-xs font-normal text-text-2">
              Fill the {formatNumber(entry.occurrences)} open application{entry.occurrences === 1 ? "" : "s"} waiting on it
            </Label>
          </div>
          <Button type="submit" size="sm" disabled={save.isPending || !trimmed} className="sm:min-w-32">
            {save.isPending ? <Loader2 className="animate-spin" /> : <Sparkles />}
            Save answer
          </Button>
        </div>
      </form>
    </Surface>
  );
}
