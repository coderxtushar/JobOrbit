"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarClock, ClipboardList, Loader2, Pencil, Plus, Trash2, UserRound } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import { useId, useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { ConfirmDialog } from "@/components/inbox/confirm-dialog";
import { EmptyState } from "@/components/shared/empty-state";
import { ErrorState, errorMessage } from "@/components/shared/query-state";
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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, type Schemas } from "@/lib/api/client";
import { api } from "@/lib/api/endpoints";
import { formatDateTime, formatRelative } from "@/lib/formatting";

import { fieldErrorText } from "./research-types";

type Round = Schemas["InterviewRoundRead"];

const schema = z.object({
  round_name: z.string().trim().min(1, "Name the round, e.g. “Technical screen”").max(120, "At most 120 characters"),
  scheduled_at: z
    .string()
    .refine((value) => !value || !Number.isNaN(new Date(value).getTime()), "Enter a valid date and time"),
  interviewer_notes: z.string().max(20_000, "At most 20,000 characters"),
  questions_asked: z
    .string()
    .refine((value) => value.split("\n").filter((line) => line.trim()).length <= 50, "At most 50 questions"),
  feedback: z.string().max(20_000, "At most 20,000 characters"),
  next_steps: z.string().max(5_000, "At most 5,000 characters"),
});

type FormValues = z.infer<typeof schema>;
type FieldName = keyof FormValues;

/** ISO with offset → the value a datetime-local input expects, in the viewer's time zone. */
function toLocalInput(value: string | null | undefined): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function toPayload(values: FormValues): Schemas["InterviewRoundCreate"] {
  return {
    round_name: values.round_name.trim(),
    // datetime-local is the viewer's local time; the API requires an explicit offset.
    scheduled_at: values.scheduled_at ? new Date(values.scheduled_at).toISOString() : null,
    interviewer_notes: values.interviewer_notes,
    questions_asked: values.questions_asked
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean),
    feedback: values.feedback,
    next_steps: values.next_steps,
  };
}

function RoundForm({
  applicationId,
  round,
  onDone,
}: {
  applicationId: number;
  round: Round | null;
  onDone: () => void;
}) {
  const id = useId();
  const client = useQueryClient();
  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      round_name: round?.round_name ?? "",
      scheduled_at: toLocalInput(round?.scheduled_at),
      interviewer_notes: round?.interviewer_notes ?? "",
      questions_asked: (round?.questions_asked ?? []).join("\n"),
      feedback: round?.feedback ?? "",
      next_steps: round?.next_steps ?? "",
    },
  });
  const { errors } = form.formState;

  const save = useMutation({
    mutationFn: (values: FormValues) =>
      round
        ? api.updateInterviewRound(round.id, toPayload(values))
        : api.createInterviewRound(applicationId, toPayload(values)),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["interview-rounds", applicationId] });
      void client.invalidateQueries({ queryKey: ["interview-prep", applicationId] });
      toast.success(round ? "Round updated" : "Round recorded");
      onDone();
    },
    onError: (error) => {
      if (error instanceof ApiError && Object.keys(error.fieldErrors).length) {
        for (const [field, message] of Object.entries(error.fieldErrors)) {
          const name = field.split(".").pop() as FieldName;
          if (name in schema.shape) form.setError(name, { message: fieldErrorText(message) });
        }
      }
    },
  });

  const field = (name: FieldName) => ({
    id: `${id}-${name}`,
    "aria-invalid": errors[name] ? true : undefined,
    "aria-describedby": errors[name] ? `${id}-${name}-error` : undefined,
    ...form.register(name),
  });

  const error = (name: FieldName) =>
    errors[name]?.message ? (
      <p id={`${id}-${name}-error`} className="text-xs text-danger">
        {errors[name]?.message}
      </p>
    ) : null;

  return (
    <form onSubmit={form.handleSubmit((values) => save.mutate(values))} className="space-y-4" noValidate>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label htmlFor={`${id}-round_name`}>Round</Label>
          <Input placeholder="Technical screen" {...field("round_name")} />
          {error("round_name")}
        </div>
        <div className="space-y-1.5">
          <Label htmlFor={`${id}-scheduled_at`}>When (your time zone)</Label>
          <Input type="datetime-local" {...field("scheduled_at")} />
          {error("scheduled_at")}
        </div>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor={`${id}-questions_asked`}>Questions asked</Label>
        <Textarea rows={3} placeholder="One question per line" {...field("questions_asked")} />
        {error("questions_asked")}
      </div>
      <div className="space-y-1.5">
        <Label htmlFor={`${id}-interviewer_notes`}>Notes</Label>
        <Textarea rows={3} placeholder="Who you met, what they focused on" {...field("interviewer_notes")} />
        {error("interviewer_notes")}
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label htmlFor={`${id}-feedback`}>Feedback received</Label>
          <Textarea rows={2} {...field("feedback")} />
          {error("feedback")}
        </div>
        <div className="space-y-1.5">
          <Label htmlFor={`${id}-next_steps`}>Next steps</Label>
          <Textarea rows={2} {...field("next_steps")} />
          {error("next_steps")}
        </div>
      </div>
      {save.isError ? (
        <p role="alert" className="rounded-md bg-danger-soft px-3 py-2 text-xs text-text-1 ring-1 ring-inset ring-danger/25">
          {errorMessage(save.error)}
        </p>
      ) : null}
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onDone} disabled={save.isPending}>
          Cancel
        </Button>
        <Button type="submit" disabled={save.isPending}>
          {save.isPending ? <Loader2 className="animate-spin" /> : null}
          {round ? "Save changes" : "Record round"}
        </Button>
      </DialogFooter>
    </form>
  );
}

function RoundCard({ round, onEdit, onDelete, index }: { round: Round; onEdit: () => void; onDelete: () => void; index: number }) {
  const reduced = useReducedMotion();
  return (
    <motion.li
      initial={reduced ? false : { opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, delay: Math.min(index, 6) * 0.04 }}
    >
      <Surface className="space-y-3 p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="font-heading text-sm font-semibold text-text-1">{round.round_name || "Unnamed round"}</p>
            <p className="mt-0.5 flex items-center gap-1 text-xs text-text-3">
              <CalendarClock className="size-3" />
              {round.scheduled_at ? formatDateTime(round.scheduled_at) : "Date not recorded"}
            </p>
          </div>
          <div className="flex shrink-0 gap-1">
            <Button size="icon-sm" variant="ghost" onClick={onEdit} aria-label={`Edit ${round.round_name || "round"}`}>
              <Pencil />
            </Button>
            <Button
              size="icon-sm"
              variant="ghost"
              onClick={onDelete}
              aria-label={`Delete ${round.round_name || "round"}`}
              className="hover:text-danger"
            >
              <Trash2 />
            </Button>
          </div>
        </div>
        {round.questions_asked.length ? (
          <div className="space-y-1">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-text-3">Questions asked</p>
            <ul className="list-disc space-y-0.5 pl-4 text-[13px] text-text-1 marker:text-text-3">
              {round.questions_asked.map((question, i) => (
                <li key={i}>{question}</li>
              ))}
            </ul>
          </div>
        ) : null}
        {(
          [
            ["Notes", round.interviewer_notes],
            ["Feedback received", round.feedback],
            ["Next steps", round.next_steps],
          ] as const
        ).map(([label, value]) =>
          value ? (
            <div key={label} className="space-y-0.5">
              <p className="text-[11px] font-semibold uppercase tracking-wider text-text-3">{label}</p>
              <p className="text-[13px] whitespace-pre-wrap text-text-2">{value}</p>
            </div>
          ) : null,
        )}
        <p className="text-[10.5px] text-text-3">Updated {formatRelative(round.updated_at)}</p>
      </Surface>
    </motion.li>
  );
}

/** The user's own interview records. Nothing here is generated. */
export function InterviewRounds({ applicationId }: { applicationId: number }) {
  const client = useQueryClient();
  const rounds = useQuery({
    queryKey: ["interview-rounds", applicationId],
    queryFn: () => api.interviewRounds(applicationId),
  });
  const [editing, setEditing] = useState<{ round: Round | null } | null>(null);
  const [deleting, setDeleting] = useState<Round | null>(null);

  const remove = useMutation({
    mutationFn: (round: Round) => api.deleteInterviewRound(round.id),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["interview-rounds", applicationId] });
      void client.invalidateQueries({ queryKey: ["interview-prep", applicationId] });
      toast.success("Round deleted");
      setDeleting(null);
    },
    onError: (error) => toast.error("The round was not deleted", { description: errorMessage(error) }),
  });

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <p className="flex items-center gap-2 text-xs text-text-3">
          <UserRound className="size-3.5" />
          Your own records of each round. JobOrbit never writes or generates these.
        </p>
        <Button size="sm" onClick={() => setEditing({ round: null })}>
          <Plus /> Record a round
        </Button>
      </div>

      {rounds.isPending ? (
        <div className="grid gap-3 md:grid-cols-2">
          <Skeleton className="h-36 rounded-xl" />
          <Skeleton className="h-36 rounded-xl" />
        </div>
      ) : rounds.isError ? (
        <ErrorState error={rounds.error} onRetry={() => rounds.refetch()} />
      ) : rounds.data.length ? (
        <ul className="grid gap-3 md:grid-cols-2">
          {rounds.data.map((round, index) => (
            <RoundCard
              key={round.id}
              round={round}
              index={index}
              onEdit={() => setEditing({ round })}
              onDelete={() => setDeleting(round)}
            />
          ))}
        </ul>
      ) : (
        <EmptyState
          icon={ClipboardList}
          title="No rounds recorded"
          description="After each interview, note what was asked, the feedback and the next step. Recording a round also marks this application as at interview stage."
          action={
            <Button size="sm" variant="outline" onClick={() => setEditing({ round: null })}>
              <Plus /> Record the first round
            </Button>
          }
        />
      )}

      <Dialog open={editing !== null} onOpenChange={(open) => (!open ? setEditing(null) : undefined)}>
        <DialogContent className="sm:max-w-xl">
          <DialogHeader>
            <DialogTitle>{editing?.round ? "Edit round" : "Record a round"}</DialogTitle>
            <DialogDescription>Saved exactly as you write it.</DialogDescription>
          </DialogHeader>
          {editing ? (
            <RoundForm
              key={editing.round?.id ?? "new"}
              applicationId={applicationId}
              round={editing.round}
              onDone={() => setEditing(null)}
            />
          ) : null}
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => (!open ? setDeleting(null) : undefined)}
        title="Delete this round?"
        description={`“${deleting?.round_name || "Unnamed round"}” and its notes will be removed. This cannot be undone.`}
        confirmLabel="Delete round"
        pending={remove.isPending}
        onConfirm={() => deleting && remove.mutate(deleting)}
      />
    </div>
  );
}
