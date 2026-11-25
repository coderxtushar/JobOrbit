"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookMarked, Loader2, Lock, Pencil, Search, Trash2 } from "lucide-react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useDeferredValue, useId, useMemo, useState } from "react";
import { toast } from "sonner";

import { EmptyState } from "@/components/shared/empty-state";
import { ErrorState, errorMessage } from "@/components/shared/query-state";
import { StatusBadge } from "@/components/shared/status-badge";
import { Surface } from "@/components/shared/surface";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { InputGroup, InputGroupAddon, InputGroupInput } from "@/components/ui/input-group";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { api } from "@/lib/api/endpoints";
import type { Schemas } from "@/lib/api/client";
import { formatDateTime, formatNumber, formatRelative } from "@/lib/formatting";

import { ConfirmDialog } from "./confirm-dialog";
import { PROVENANCE } from "./labels";

type Saved = Schemas["SavedAnswerRead"];

/** Every reusable answer, searchable, with edit and delete. */
export function AnswerBank() {
  const answers = useQuery({ queryKey: ["answers"], queryFn: api.answers });
  const [search, setSearch] = useState("");
  const deferred = useDeferredValue(search);
  const [editing, setEditing] = useState<Saved | null>(null);
  const [deleting, setDeleting] = useState<Saved | null>(null);
  const reduced = useReducedMotion();

  const filtered = useMemo(() => {
    const needle = deferred.trim().toLowerCase();
    const rows = answers.data ?? [];
    if (!needle) return rows;
    return rows.filter((row) =>
      [row.question, row.question_key, row.answer].some((text) => text.toLowerCase().includes(needle)),
    );
  }, [answers.data, deferred]);

  if (answers.isLoading) {
    return (
      <div className="space-y-2">
        <Skeleton className="h-9 w-full max-w-sm" />
        {Array.from({ length: 4 }).map((_, index) => (
          <Skeleton key={index} className="h-20 w-full rounded-xl" />
        ))}
      </div>
    );
  }
  if (answers.isError) return <ErrorState error={answers.error} onRetry={() => answers.refetch()} />;

  const total = answers.data?.length ?? 0;

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <InputGroup className="sm:max-w-sm">
          <InputGroupAddon>
            <Search />
          </InputGroupAddon>
          <InputGroupInput
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search questions, keys or answers"
            aria-label="Search the answer bank"
          />
        </InputGroup>
        <p className="text-xs text-text-3 tabular">
          {deferred.trim() ? `${formatNumber(filtered.length)} of ${formatNumber(total)}` : formatNumber(total)} saved
          answer{total === 1 ? "" : "s"}
        </p>
      </div>

      {total === 0 ? (
        <EmptyState
          icon={BookMarked}
          title="Your answer bank is empty"
          description="Answers you give in the action inbox are saved here and reused on later applications. Only answers you typed, or that come from a verified profile field, can be saved."
        />
      ) : filtered.length === 0 ? (
        <EmptyState compact icon={Search} title="No saved answer matches" description={`Nothing contains “${deferred.trim()}”.`} />
      ) : (
        <ul className="space-y-2">
          <AnimatePresence initial={false}>
            {filtered.map((row) => {
              const provenance = PROVENANCE[row.provenance] ?? {
                label: row.provenance,
                tone: "neutral" as const,
                hint: "",
              };
              return (
                <motion.li
                  key={row.question_key}
                  layout={!reduced}
                  initial={reduced ? false : { opacity: 0, y: 4 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={reduced ? { opacity: 0 } : { opacity: 0, y: -4 }}
                  transition={{ duration: 0.2, ease: [0.22, 1, 0.36, 1] }}
                >
                  <Surface className="flex flex-col gap-3 p-4 transition-colors hover:border-line-strong md:flex-row md:items-start">
                    <div className="min-w-0 flex-1 space-y-2">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <span tabIndex={0} className="rounded-full">
                              <StatusBadge tone={provenance.tone}>{provenance.label}</StatusBadge>
                            </span>
                          </TooltipTrigger>
                          {provenance.hint ? <TooltipContent className="max-w-xs">{provenance.hint}</TooltipContent> : null}
                        </Tooltip>
                        {row.is_sensitive ? (
                          <StatusBadge tone="warning">
                            <Lock className="size-3" /> Sensitive
                          </StatusBadge>
                        ) : null}
                        <span className="font-mono text-[11px] text-text-3">{row.question_key}</span>
                      </div>
                      <p className="text-sm font-medium text-text-1">{row.question || row.question_key}</p>
                      <p className="rounded-lg bg-surface-2/70 px-3 py-2 text-sm whitespace-pre-wrap text-text-1 ring-1 ring-inset ring-line">
                        {row.answer}
                      </p>
                      <p className="flex flex-wrap gap-x-3 gap-y-1 text-[11.5px] text-text-3">
                        <span className="tabular">
                          Used {formatNumber(row.times_used)} time{row.times_used === 1 ? "" : "s"}
                        </span>
                        <span title={formatDateTime(row.last_used_at)}>
                          Last used {row.last_used_at ? formatRelative(row.last_used_at) : "never"}
                        </span>
                        <span title={formatDateTime(row.updated_at)}>Updated {formatRelative(row.updated_at)}</span>
                      </p>
                    </div>
                    <div className="flex shrink-0 gap-1.5 md:flex-col">
                      <Button size="sm" variant="outline" onClick={() => setEditing(row)}>
                        <Pencil /> Edit
                      </Button>
                      <Button size="sm" variant="ghost" className="text-danger hover:text-danger" onClick={() => setDeleting(row)}>
                        <Trash2 /> Delete
                      </Button>
                    </div>
                  </Surface>
                </motion.li>
              );
            })}
          </AnimatePresence>
        </ul>
      )}

      {editing ? <EditAnswerDialog key={editing.question_key} answer={editing} onClose={() => setEditing(null)} /> : null}
      <DeleteAnswerDialog answer={deleting} onClose={() => setDeleting(null)} />
    </div>
  );
}

function EditAnswerDialog({ answer, onClose }: { answer: Saved; onClose: () => void }) {
  const queryClient = useQueryClient();
  const fieldId = useId();
  const [text, setText] = useState(answer.answer);
  const [applyToOpen, setApplyToOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = useMutation({
    mutationFn: () =>
      api.saveAnswer(answer.question_key, {
        answer: text.trim(),
        question: answer.question,
        apply_to_open_applications: applyToOpen,
      }),
    onSuccess: (result) => {
      toast.success("Answer updated", {
        description: applyToOpen
          ? `Filled ${formatNumber(result.applications_updated)} open application${result.applications_updated === 1 ? "" : "s"} that were still waiting on it.`
          : "Applications already prepared keep the answer they had.",
      });
      void queryClient.invalidateQueries({ queryKey: ["answers"] });
      void queryClient.invalidateQueries({ queryKey: ["inbox"] });
      void queryClient.invalidateQueries({ queryKey: ["nav", "inbox"] });
      onClose();
    },
    onError: (failure) => setError(errorMessage(failure)),
  });

  return (
    <Dialog open onOpenChange={(open) => (!open && !save.isPending ? onClose() : undefined)}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Edit saved answer</DialogTitle>
          <DialogDescription className="leading-relaxed">{answer.question || answer.question_key}</DialogDescription>
        </DialogHeader>
        <form
          id={`${fieldId}-form`}
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            if (!text.trim()) {
              setError("An answer cannot be blank. Delete it instead if you no longer want it.");
              return;
            }
            save.mutate();
          }}
        >
          <div className="space-y-1.5">
            <Label htmlFor={`${fieldId}-text`}>Answer</Label>
            <Textarea
              id={`${fieldId}-text`}
              value={text}
              onChange={(event) => {
                setText(event.target.value);
                if (error) setError(null);
              }}
              rows={4}
              aria-invalid={error ? true : undefined}
              aria-describedby={error ? `${fieldId}-error` : undefined}
              autoFocus
            />
            {error ? (
              <p id={`${fieldId}-error`} role="alert" className="text-xs text-danger">
                {error}
              </p>
            ) : null}
          </div>
          <div className="flex items-start gap-2">
            <Switch id={`${fieldId}-apply`} checked={applyToOpen} onCheckedChange={setApplyToOpen} className="mt-0.5" />
            <Label htmlFor={`${fieldId}-apply`} className="flex-col items-start gap-0.5 font-normal">
              <span className="text-sm text-text-1">Also fill open applications still waiting on it</span>
              <span className="text-xs text-text-3">
                Only applications with this question unanswered are filled. Submitted applications are never rewritten.
              </span>
            </Label>
          </div>
        </form>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={save.isPending}>
            Cancel
          </Button>
          <Button type="submit" form={`${fieldId}-form`} disabled={save.isPending}>
            {save.isPending ? <Loader2 className="animate-spin" /> : null}
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function DeleteAnswerDialog({ answer, onClose }: { answer: Saved | null; onClose: () => void }) {
  const queryClient = useQueryClient();
  const remove = useMutation({
    mutationFn: (key: string) => api.deleteAnswer(key),
    onSuccess: () => {
      toast.success("Saved answer deleted");
      void queryClient.invalidateQueries({ queryKey: ["answers"] });
      void queryClient.invalidateQueries({ queryKey: ["inbox"] });
      onClose();
    },
    onError: (failure) => toast.error("Could not delete the answer", { description: errorMessage(failure) }),
  });
  return (
    <ConfirmDialog
      open={answer !== null}
      onOpenChange={(open) => (!open ? onClose() : undefined)}
      title="Delete this saved answer?"
      description={
        <>
          Future applications will ask you again for{" "}
          <span className="font-medium text-text-1">{answer?.question || answer?.question_key}</span>. Applications that
          already used it keep the answer they received.
        </>
      }
      confirmLabel="Delete answer"
      pending={remove.isPending}
      onConfirm={() => answer && remove.mutate(answer.question_key)}
    />
  );
}
